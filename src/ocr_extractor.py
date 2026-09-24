import re
import os
import json
import datetime

class DocumentExtractor:
    def __init__(self):
        pass

    def extract_fields_from_text(self, text: str, filename: str = "") -> dict:
        """
        Analisa o texto extraído por OCR e extrai todos os campos financeiros,
        ligações entre documentos, estado de pagamento e notas de validação.
        """
        text_upper = text.upper()
        
        # 1. Tipo de Documento e Categorização
        tipo_doc = "OUTRO"
        categoria_pasta = "Pendentes_Revisao"
        
        if "RESUMO DE FACTURAS" in text_upper or "RESUMO DE FATURAS" in text_upper or "EXTRACTO" in text_upper:
            tipo_doc = "LOTE_FATURAS"
            categoria_pasta = "Lotes_Faturas"
        elif "NOTA DE CRÉDITO" in text_upper or "NOTA DE CREDITO" in text_upper or "NOTA CREDITO" in text_upper:
            tipo_doc = "NOTA_CREDITO"
            categoria_pasta = "Notas_Credito"
        elif "GUIA DE REMESSA" in text_upper or "GUIA DE TRANSPORTE" in text_upper or "GUIA N" in text_upper:
            tipo_doc = "GUIA_REMESSA"
            categoria_pasta = "Faturas"
        elif "FACTURA" in text_upper or "FATURA" in text_upper or "FT " in text_upper:
            tipo_doc = "FATURA"
            categoria_pasta = "Faturas"

        # 2. Fornecedor & NIF
        fornecedor = "DESCONHECIDO"
        nif_fornecedor = ""
        
        if "COOPROFAR" in text_upper or "500336512" in text_upper or "500 336 512" in text_upper:
            fornecedor = "COOPROFAR"
            nif_fornecedor = "500336512"
        elif "ALLIANCE" in text_upper:
            fornecedor = "ALLIANCE_HEALTHCARE"
            nif_fornecedor = "507821831"
        elif "FARMAVENDA" in text_upper:
            fornecedor = "FARMAVENDA"

        if not nif_fornecedor:
            nif_match = re.search(r'(?:NIF|CONTRIBUINTE|CONTRIB\.?)\s*(?:N\.º|Nº)?\s*(?:PT)?\s*([569]\d{2}\s*\d{3}\s*\d{3})', text_upper)
            if nif_match:
                nif_fornecedor = nif_match.group(1).replace(" ", "")

        # 3. Número do Documento
        num_doc = ""
        if tipo_doc == "FATURA":
            doc_match = re.search(r'F\s*F\s*/\s*(\d{7,10})', text_upper)
            if not doc_match:
                doc_match = re.search(r'FACTURA\s*([A-Z0-9/]+)', text_upper)
            if not doc_match:
                doc_match = re.search(r'(?:N\.º\s*DOC|Nº\s*DOC)\.?\s*(\d{7,10})', text_upper)
            if doc_match:
                num_doc = doc_match.group(1).strip()
        elif tipo_doc == "LOTE_FATURAS":
            doc_match = re.search(r'RESUMO DE FACTURAS N\.?º?\s*(\d{6,10})', text_upper)
            if not doc_match:
                doc_match = re.search(r'N\.?º?\s*(\d{7,10})', text_upper)
            if doc_match:
                num_doc = doc_match.group(1).strip()
        elif tipo_doc == "NOTA_CREDITO":
            doc_match = re.search(r'(?:NOTA DE CRÉDITO|NOTA DE CREDITO)\s*N\.?º?\s*([A-Z0-9/]+)', text_upper)
            if not doc_match:
                doc_match = re.search(r'\b\d{7,8}\b', text)
                if doc_match:
                    num_doc = doc_match.group(0)

        if not num_doc:
            digits = re.findall(r'\b\d{7,8}\b', text)
            if digits:
                num_doc = digits[0]
            else:
                num_doc = filename.replace(".pdf", "")

        # 4. Data do Documento
        data_doc = ""
        dates = re.findall(r'\b(202\d[-/]\d{2}[-/]\d{2})\b', text)
        if not dates:
            dates = re.findall(r'\b(\d{2}[-/]\d{2}[-/]202\d)\b', text)
        
        if dates:
            raw_date = dates[0].replace("/", "-")
            parts = raw_date.split("-")
            if len(parts[0]) == 4:
                data_doc = raw_date
            else:
                data_doc = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            data_doc = datetime.date.today().strftime("%Y-%m-%d")

        # 5. Valor Total (€)
        valor_total = 0.0
        val_match = re.search(r'TOTAL\s*(?:LIQUIDO|LÍQUIDO|EUR|ETICO)?\s*[\:\=]?\s*([\d\.\,]+)', text_upper)
        if not val_match:
            val_match = re.search(r'VALOR A PAGAR\s*([\d\.\,]+)', text_upper)
        if not val_match:
            val_match = re.search(r'([\d]{1,5}[\.\,]\d{2})\s*(?:EUR|€)?', text_upper)
            
        if val_match:
            val_str = val_match.group(1).replace(".", "").replace(",", ".")
            try:
                valor_total = float(val_str)
            except ValueError:
                valor_total = 0.0

        # 6. Estado de Pagamento (Pago / Não Pago / Pendente)
        estado_pagamento = "Pendente"
        if "PAGO" in text_upper or "LIQUIDADO" in text_upper or "PRONTO PAGAMENTO" in text_upper:
            estado_pagamento = "Pago"
        elif "DATA LIMITE PAGAMENTO" in text_upper or "VENCIMENTO" in text_upper or "A LIQUIDAR" in text_upper:
            estado_pagamento = "Não Pago"
        elif tipo_doc == "NOTA_CREDITO":
            estado_pagamento = "Creditado / Reembolsado"

        # 7. Documentos Relacionados
        doc_relacionados = []
        if tipo_doc == "NOTA_CREDITO":
            # Procurar referência a fatura original
            ref_matches = re.findall(r'(?:REF|FATURA|FACTURA|V/REF)\s*[\:\.]?\s*([A-Z0-9/]+)', text_upper)
            for ref in ref_matches:
                if len(ref) >= 5 and ref not in doc_relacionados:
                    doc_relacionados.append(f"Ref. Fatura {ref}")
        elif tipo_doc == "LOTE_FATURAS":
            # Procurar lista de faturas no resumo (ex: Fact. 29916327)
            fact_list = re.findall(r'FACT\.?\s*(\d{7,10})', text_upper)
            if fact_list:
                doc_relacionados = [f"Fatura {f}" for f in set(fact_list)]

        doc_relacionados_str = ", ".join(doc_relacionados) if doc_relacionados else "Nenhum"

        # 8. Validação e Notificação de Ficheiro Não Enquadrado
        estado_processamento = "Validado"
        observacoes = "Documento processado com sucesso."

        if fornecedor == "DESCONHECIDO" or len(text.strip()) < 15 or tipo_doc == "OUTRO":
            estado_processamento = "Necessita Revisão"
            observacoes = "Não foi possível enquadrar completamente o documento. Necessita de revisão manual."
            categoria_pasta = "Pendentes_Revisao"

        return {
            "id_documento": num_doc,
            "tipo_documento": tipo_doc,
            "categoria_pasta": categoria_pasta,
            "fornecedor": fornecedor,
            "nif_fornecedor": nif_fornecedor,
            "data_documento": data_doc,
            "valor_total": valor_total,
            "estado_pagamento": estado_pagamento,
            "documentos_relacionados": doc_relacionados_str,
            "estado_processamento": estado_processamento,
            "observacoes": observacoes,
            "ficheiro_original": filename
        }
