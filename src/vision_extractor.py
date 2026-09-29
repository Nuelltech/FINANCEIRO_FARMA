import os
import json
import base64
import re
from io import BytesIO
import requests
import pymupdf
from PIL import Image

DEFAULT_SYSTEM_PROMPT = """Você é um especialista em contabilidade e análise de documentos financeiros de farmácias em Portugal.
Sua tarefa é analisar o documento (fatura, nota de crédito, resumo de lote ou outro) e extrair EXATAMENTE os seguintes campos em formato JSON válido:

{
  "tipo_documento": "Fatura | Nota de Crédito | Resumo de Lote | Outro",
  "fornecedor": "string (nome do emissor/fornecedor)",
  "nif_fornecedor": "string ou null (NIF/NIPC de 9 dígitos do fornecedor/emissor)",
  "farmacia": "Farmácia Baptista | Farmácia Campeã | Indeterminado",
  "numero_documento": "string ou null",
  "data_documento": "AAAA-MM-DD ou null (Data de Emissão / Fatura)",
  "data_vencimento": "AAAA-MM-DD ou null (Data Limite de Pagamento / Vencimento)",
  "valor_total": number ou null,
  "moeda": "EUR",
  "numero_lote": "string ou null (só Resumo de Lote)",
  "faturas_agregadas": [
    {"numero": "string", "valor": number}
  ],
  "confianca": "alta | media | baixa",
  "motivo_baixa_confianca": "string ou null"
}

REGRAS ESTRITAS DE EXTRAÇÃO:
1. Responda APENAS com o JSON válido, sem texto explicativo antes ou depois.
2. Distinga claramente a "data_documento" (Data de Emissão/Emitido em) da "data_vencimento" (Data Limite de Pagamento / Vencimento em).
3. Para "data_vencimento", procure com extrema atenção por rótulos no documento como: "Vencimento em", "Data Vencimento", "Vencimento", "Data Limite de Pagamento", "Pagar até", "Venc.".
4. Se o documento contiver uma Condição de Pagamento (ex: "Cond. de Pagamento: 45 Dias", "30 Dias", "60 Dias") e a data de vencimento não estiver escrita por extenso, CALCULE a data de vencimento somando esse número de dias à data_documento (exemplo: Emitido em 2026-09-10 com 45 Dias -> Vencimento em 2026-10-25).
5. NUNCA assuma data_vencimento igual a data_documento se existir um prazo de vencimento futuro ou condição de pagamento diferente de Pronto Pagamento.
6. Se for um "Resumo de Lote", inclua "numero_lote" e no array "faturas_agregadas" a lista de todas as faturas e notas de crédito individuais que compõem o lote com números e valores (se for nota de crédito ou devolução a abater, indique o valor correspondente).
7. Moeda deve ser sempre "EUR". Datas no formato YYYY-MM-DD. Valores numéricos como float (ex: 1250.45).
8. Para "nif_fornecedor": extraia o NIF/NIPC do EMISSOR (fornecedor) do documento. Em Portugal aparece tipicamente junto aos labels "NIF:", "NIPC:", "Contribuinte:" ou como número de 9 dígitos no cabeçalho/rodapé. Se não for visível, devolva null. NÃO confunda com o NIF da farmácia (destinatário).
9. Para "motivo_baixa_confianca": SEMPRE preencha este campo quando "confianca" for "baixa" ou "media". Explique de forma clara e específica O QUE o revisor humano deve verificar ou corrigir no documento. Exemplos: "Número de documento ilegível — verificar manualmente", "Valor rasurado na página 2", "Não é possível confirmar se a farmácia destinatária é Baptista ou Campeã — verificar carimbo", "Documento parece ser uma guia de remessa, não uma fatura — confirmar tipo". Se confiança for "alta", deixe null.
"""

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

class VisionExtractor:
    """
    Extrator Multimodal com Visão LLM (Claude REST API nativa / Gemini 1.5).
    Implementado com a mesma arquitetura REST direta do projeto trading-agent (claude_analyzer.py).
    """
    def __init__(self, provider: str = "anthropic"):
        self.provider = provider.lower()
        self.anthropic_key = (
            os.getenv("ANTHROPIC_API_KEY", "").strip() or 
            os.getenv("ANTHROPIC_API_KEY_FARMA", "").strip() or 
            os.getenv("ANTHROPIC_API_KEY_TRADING", "").strip()
        )
        self.gemini_key = (os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip())

    def pdf_to_base64_images(self, pdf_path: str, dpi: int = 150) -> list:
        """Converte cada página do PDF numa imagem PNG codificada em Base64."""
        images = []
        doc = pymupdf.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            zoom = dpi / 72
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            images.append(img_b64)
        return images

    def extract_from_pdf(self, pdf_path: str, system_prompt: str = None) -> dict:
        """Processa o PDF através de Visão LLM usando a API REST nativa."""
        prompt_to_use = system_prompt or DEFAULT_SYSTEM_PROMPT
        filename = os.path.basename(pdf_path)
        
        if self.anthropic_key:
            return self._extract_with_claude_rest(pdf_path, prompt_to_use)
        elif self.gemini_key:
            return self._extract_with_gemini(pdf_path, prompt_to_use)
        else:
            print(f"  [Aviso] Nenhuma API Key de LLM encontrada. A usar extrator heurístico/mock para {filename}.")
            return self._heuristic_fallback(pdf_path)

    def _extract_with_claude_rest(self, pdf_path: str, system_prompt: str) -> dict:
        """Chamada REST nativa idêntica ao módulo claude_analyzer.py do trading-agent."""
        images_b64 = self.pdf_to_base64_images(pdf_path)
        
        message_content = []
        for b64_img in images_b64:
            message_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_img
                }
            })
        message_content.append({
            "type": "text",
            "text": "Analise estas imagens do documento financeiro e extraia a informação estritamente de acordo com o esquema JSON pedido, prestando especial atenção à 'data_vencimento' (ex: Vencimento em)."
        })
        
        primary_model = os.getenv("CLAUDE_MODEL", "").strip() or "claude-3-5-sonnet-20240620"
        candidate_models = [
            primary_model,
            "claude-3-5-sonnet-20240620",
            "claude-sonnet-4-6",
            "claude-3-7-sonnet-20250219",
            "claude-3-haiku-20240307"
        ]
        
        models_to_try = []
        for m in candidate_models:
            if m and m not in models_to_try:
                models_to_try.append(m)

        headers = {
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        last_error_msg = ""
        for target_model in models_to_try:
            payload = {
                "model": target_model,
                "max_tokens": 2048,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": message_content}
                ]
            }

            try:
                res = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=90)
                if res.status_code == 200:
                    data = res.json()
                    raw_text = data["content"][0]["text"]
                    return self._parse_json_response(raw_text, pdf_path)
                else:
                    print(f"  [Aviso Anthropic REST] Modelo '{target_model}' devolveu Status {res.status_code}: {res.text}")
                    last_error_msg = f"HTTP {res.status_code}: {res.text}"
            except Exception as e:
                print(f"  [Aviso Anthropic REST] Exceção ao chamar modelo '{target_model}': {e}")
                last_error_msg = str(e)

        return {
            "tipo_documento": "Outro",
            "fornecedor": "DESCONHECIDO",
            "farmacia": "Indeterminado",
            "numero_documento": None,
            "data_documento": None,
            "data_vencimento": None,
            "valor_total": None,
            "moeda": "EUR",
            "numero_lote": None,
            "faturas_agregadas": [],
            "confianca": "baixa",
            "motivo_baixa_confianca": f"Falha nas chamadas REST da Anthropic API: {last_error_msg}"
        }

    def _extract_with_gemini(self, pdf_path: str, system_prompt: str) -> dict:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=self.gemini_key)
        images_b64 = self.pdf_to_base64_images(pdf_path)
        
        contents = []
        for b64_img in images_b64:
            img_bytes = base64.b64decode(b64_img)
            contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))
        
        contents.append(system_prompt + "\nAnalise as imagens e responda em JSON.")
        
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=contents
        )
        
        return self._parse_json_response(response.text, pdf_path)

    def _parse_json_response(self, raw_text: str, pdf_path: str) -> dict:
        try:
            cleaned = re.sub(r'```json\s*', '', raw_text)
            cleaned = re.sub(r'```\s*$', '', cleaned).strip()
            data = json.loads(cleaned)
            return data
        except Exception as e:
            print(f"  Error parsing JSON response: {e}")
            return {
                "tipo_documento": "Outro",
                "fornecedor": "DESCONHECIDO",
                "farmacia": "Indeterminado",
                "numero_documento": None,
                "data_documento": None,
                "data_vencimento": None,
                "valor_total": None,
                "moeda": "EUR",
                "numero_lote": None,
                "faturas_agregadas": [],
                "confianca": "baixa",
                "motivo_baixa_confianca": f"Falha ao interpretar resposta JSON do LLM: {str(e)}"
            }

    def _heuristic_fallback(self, pdf_path: str) -> dict:
        import datetime
        doc = pymupdf.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        
        text_upper = text.upper()
        filename = os.path.basename(pdf_path)
        
        if "RESUMO" in text_upper or "EXTRACTO" in text_upper or "LOTE" in filename.upper():
            tipo = "Resumo de Lote"
        elif "CRÉDITO" in text_upper or "CREDITO" in text_upper:
            tipo = "Nota de Crédito"
        elif "FACTURA" in text_upper or "FATURA" in text_upper:
            tipo = "Fatura"
        else:
            tipo = "Outro"

        fornecedor = "COOPROFAR" if "COOPROFAR" in text_upper else ("ALLIANCE HEALTHCARE" if "ALLIANCE" in text_upper else "DESCONHECIDO")
        
        if "BAPTISTA" in text_upper or "BAPTISTA" in filename.upper():
            farmacia = "Farmácia Baptista"
        elif "CAMPEÃ" in text_upper or "CAMPEA" in text_upper or "CAMPEA" in filename.upper():
            farmacia = "Farmácia Campeã"
        else:
            farmacia = "Indeterminado"

        num_doc_match = re.search(r'(?:FFI|FFL|\d{7,9})', filename)
        num_doc = num_doc_match.group(0) if num_doc_match else None

        date_match = re.search(r'202\d-\d{2}-\d{2}', filename)
        data_doc = date_match.group(0) if date_match else None

        # Procurar data de vencimento explícita no texto (ex: Vencimento em: 2026-10-25)
        venc_match = re.search(r'(?:vencimento|venc\.?|pagar\s+at[é|e]|data\s+limite)(?:\s+em)?\s*:?\s*(\d{4}[-\/\.]\d{2}[-\/\.]\d{2}|\d{2}[-\/\.]\d{2}[-\/\.]\d{4})', text, re.IGNORECASE)
        data_venc = None
        if venc_match:
            raw_venc = venc_match.group(1).replace(".", "-").replace("/", "-")
            parts = raw_venc.split("-")
            if len(parts) == 3:
                if len(parts[0]) == 2 and len(parts[2]) == 4:
                    data_venc = f"{parts[2]}-{parts[1]}-{parts[0]}"
                else:
                    data_venc = raw_venc

        # Se não houver data explícita, procurar por Condição de Pagamento (ex: 45 Dias)
        if not data_venc and data_doc:
            cond_match = re.search(r'cond\.?\s+(?:de\s+)?pagamento\s*:?\s*(\d+)\s*dias', text, re.IGNORECASE)
            if cond_match:
                days = int(cond_match.group(1))
                try:
                    doc_dt = datetime.datetime.strptime(data_doc, "%Y-%m-%d")
                    venc_dt = doc_dt + datetime.timedelta(days=days)
                    data_venc = venc_dt.strftime("%Y-%m-%d")
                except Exception:
                    data_venc = data_doc

        val_match = re.search(r'TOTAL\s*:?\s*([\d\.\,]+)', text_upper)
        valor_total = float(val_match.group(1).replace(".", "").replace(",", ".")) if val_match else None

        confianca = "alta" if (num_doc and data_doc and valor_total and fornecedor != "DESCONHECIDO") else "baixa"
        motivo = None if confianca == "alta" else "Modo de simulação sem API key / campos em falta"

        return {
            "tipo_documento": tipo,
            "fornecedor": fornecedor,
            "farmacia": farmacia,
            "numero_documento": num_doc,
            "data_documento": data_doc,
            "data_vencimento": data_venc or data_doc,
            "valor_total": valor_total,
            "moeda": "EUR",
            "numero_lote": None,
            "faturas_agregadas": [],
            "confianca": confianca,
            "motivo_baixa_confianca": motivo
        }
