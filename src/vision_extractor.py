import os
import json
import base64
import re
from io import BytesIO
import pymupdf
from PIL import Image

class VisionExtractor:
    """
    Extrator Multimodal com Visão LLM (Claude 3.5 Sonnet / Gemini 1.5).
    Converte páginas PDF em imagens PNG e envia para a API do LLM solicitando JSON estruturado.
    """
    def __init__(self, provider: str = "anthropic"):
        self.provider = provider.lower()
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        
        self.system_prompt = """Você é um especialista em contabilidade e análise de documentos financeiros de farmácias em Portugal.
Sua tarefa é analisar o documento (fatura, nota de crédito, resumo de lote ou outro) e extrair EXATAMENTE os seguintes campos em formato JSON válido:

{
  "tipo_documento": "Fatura | Nota de Crédito | Resumo de Lote | Outro",
  "fornecedor": "string",
  "farmacia": "Farmácia Baptista | Farmácia Campeã | Indeterminado",
  "numero_documento": "string ou null",
  "data_documento": "AAAA-MM-DD ou null",
  "valor_total": number ou null,
  "moeda": "EUR",
  "confianca": "alta | media | baixa",
  "motivo_baixa_confianca": "string ou null",
  "faturas_agregadas": [
    {"numero_documento": "string", "valor": number}
  ]
}

REGRAS ESTRITAS:
1. Responda APENAS com o JSON válido, sem texto explicativo antes ou depois.
2. Nomes de farmácia aceites: "Farmácia Baptista" ou "Farmácia Campeã". Se não for possível determinar com certeza, use "Indeterminado".
3. Se a qualidade da imagem for má, se houver dúvida sobre dígitos, ou se faltar algum campo obrigatório (número, data, valor, fornecedor), defina "confianca": "baixa" e preencha "motivo_baixa_confianca".
4. Para "Resumo de Lote", inclua no array "faturas_agregadas" a lista das faturas individuais listadas no documento com os respetivos números e valores.
5. Moeda deve ser sempre "EUR". Datas no formato YYYY-MM-DD. Valores numéricos como float (ex: 1250.45).
"""

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

    def extract_from_pdf(self, pdf_path: str) -> dict:
        """Processa o PDF através de Visão LLM com fallback gracioso se não houver API key."""
        filename = os.path.basename(pdf_path)
        
        # Verificar se existem API keys ativas
        if self.provider == "anthropic" and self.anthropic_key:
            return self._extract_with_claude(pdf_path)
        elif self.provider == "gemini" and self.gemini_key:
            return self._extract_with_gemini(pdf_path)
        elif self.anthropic_key:
            return self._extract_with_claude(pdf_path)
        elif self.gemini_key:
            return self._extract_with_gemini(pdf_path)
        else:
            print(f"  [Aviso] Nenhuma API Key de LLM encontrada. A usar extrator heurístico/mock para {filename}.")
            return self._heuristic_fallback(pdf_path)

    def _extract_with_claude(self, pdf_path: str) -> dict:
        import anthropic
        client = anthropic.Anthropic(api_key=self.anthropic_key)
        images_b64 = self.pdf_to_base64_images(pdf_path)
        
        content = []
        for b64_img in images_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_img
                }
            })
        content.append({
            "type": "text",
            "text": "Analise estas imagens do documento financeiro e extraia a informação estritamente de acordo com o esquema JSON pedido."
        })
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            system=self.system_prompt,
            messages=[{"role": "user", "content": content}]
        )
        
        raw_text = response.content[0].text
        return self._parse_json_response(raw_text, pdf_path)

    def _extract_with_gemini(self, pdf_path: str) -> dict:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=self.gemini_key)
        images_b64 = self.pdf_to_base64_images(pdf_path)
        
        contents = []
        for b64_img in images_b64:
            img_bytes = base64.b64decode(b64_img)
            contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))
        
        contents.append(self.system_prompt + "\nAnalise as imagens e responda em JSON.")
        
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=contents
        )
        
        return self._parse_json_response(response.text, pdf_path)

    def _parse_json_response(self, raw_text: str, pdf_path: str) -> dict:
        """Extrai e limpa a resposta JSON da resposta do LLM."""
        try:
            # Remover eventuais blocos de código ```json ... ```
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
                "valor_total": None,
                "moeda": "EUR",
                "confianca": "baixa",
                "motivo_baixa_confianca": f"Falha ao interpretar resposta JSON do LLM: {str(e)}",
                "faturas_agregadas": []
            }

    def _heuristic_fallback(self, pdf_path: str) -> dict:
        """Fallback por texto/regex para testes locais quando não há chaves de API ligadas."""
        doc = pymupdf.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        
        text_upper = text.upper()
        filename = os.path.basename(pdf_path)
        
        # Tipo
        if "RESUMO" in text_upper or "EXTRACTO" in text_upper or "LOTE" in filename.upper():
            tipo = "Resumo de Lote"
        elif "CRÉDITO" in text_upper or "CREDITO" in text_upper:
            tipo = "Nota de Crédito"
        elif "FACTURA" in text_upper or "FATURA" in text_upper:
            tipo = "Fatura"
        else:
            tipo = "Outro"

        # Fornecedor
        fornecedor = "COOPROFAR" if "COOPROFAR" in text_upper else ("ALLIANCE HEALTHCARE" if "ALLIANCE" in text_upper else "DESCONHECIDO")
        
        # Farmácia
        if "BAPTISTA" in text_upper or "BAPTISTA" in filename.upper():
            farmacia = "Farmácia Baptista"
        elif "CAMPEÃ" in text_upper or "CAMPEA" in text_upper or "CAMPEA" in filename.upper():
            farmacia = "Farmácia Campeã"
        else:
            farmacia = "Indeterminado"

        # Num doc
        num_doc_match = re.search(r'(?:FFI|FFL|\d{7,9})', filename)
        num_doc = num_doc_match.group(0) if num_doc_match else None

        # Data
        date_match = re.search(r'202\d-\d{2}-\d{2}', filename)
        data_doc = date_match.group(0) if date_match else None

        # Valor
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
            "valor_total": valor_total,
            "moeda": "EUR",
            "confianca": confianca,
            "motivo_baixa_confianca": motivo,
            "faturas_agregadas": []
        }
