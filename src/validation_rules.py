import os

class ValidationRules:
    """
    Motor de Validação de Regras de Negócio e Segurança de Dados.
    Aplica o duplo filtro de confiança, tratamento de duplicados e validação de lotes.
    """
    
    MANDATORY_FIELDS = ["numero_documento", "valor_total", "fornecedor", "data_documento"]

    @staticmethod
    def validate_extraction(raw_data: dict, filename: str) -> dict:
        """
        Aplica as regras de validação cruzada e o duplo filtro de confiança do PRD.
        """
        processed = dict(raw_data)
        confianca_original = str(processed.get("confianca", "baixa")).lower()
        motivos = []

        if processed.get("motivo_baixa_confianca"):
            motivos.append(str(processed.get("motivo_baixa_confianca")))

        # 1. Duplo Filtro de Confiança: Verificar campos obrigatórios
        missing_fields = []
        for field in ValidationRules.MANDATORY_FIELDS:
            val = processed.get(field)
            if val is None or str(val).strip() == "" or str(val).strip().lower() == "null":
                missing_fields.append(field)

        if missing_fields:
            confianca_final = "baixa"
            motivos.append(f"Campos obrigatórios ausentes: {', '.join(missing_fields)}")
        elif confianca_original == "baixa":
            confianca_final = "baixa"
        else:
            confianca_final = "alta" if confianca_original in ["alta", "alta_confianca"] else "media"

        # 2. Normalização do Tipo de Documento
        tipo_raw = str(processed.get("tipo_documento", "Outro")).strip()
        tipo_lower = tipo_raw.lower()
        
        if "resumo" in tipo_lower or "lote" in tipo_lower:
            tipo_normalizado = "Resumo de Lote"
        elif "crédito" in tipo_lower or "credito" in tipo_lower:
            tipo_normalizado = "Nota de Crédito"
        elif "fatura" in tipo_lower or "factura" in tipo_lower:
            tipo_normalizado = "Fatura"
        else:
            tipo_normalizado = "A Rever" if confianca_final == "baixa" else "Outro"

        # 3. Normalização da Farmácia
        farmacia_raw = str(processed.get("farmacia", "Indeterminado")).strip()
        if "baptista" in farmacia_raw.lower():
            farmacia_normalizada = "Farmácia Baptista"
        elif "campeã" in farmacia_raw.lower() or "campea" in farmacia_raw.lower():
            farmacia_normalizada = "Farmácia Campeã"
        else:
            farmacia_normalizada = "Indeterminado"
            if confianca_final != "baixa":
                confianca_final = "media"
                motivos.append("Farmácia não identificada com clareza")

        # 4. Estado de Processamento e Nota
        if confianca_final == "baixa":
            nota = f"Processo manual necessário: {'; '.join(motivos)}" if motivos else "Processo manual necessário (baixa confiança)"
            categoria_pasta = "A Rever"
        else:
            nota = f"Lote associado: {processed.get('numero_lote_associado')}" if processed.get('numero_lote_associado') else ""
            categoria_pasta = ValidationRules.determine_folder_category(tipo_normalizado)

        processed.update({
            "tipo_documento": tipo_normalizado,
            "farmacia": farmacia_normalizada,
            "confianca": confianca_final.capitalize(),
            "motivo_baixa_confianca": "; ".join(motivos) if motivos else None,
            "categoria_pasta": categoria_pasta,
            "nota": nota
        })

        return processed

    @staticmethod
    def determine_folder_category(tipo_doc: str) -> str:
        """Mapeia o tipo de documento para a subpasta no Google Drive."""
        if tipo_doc == "Fatura":
            return "Faturas"
        elif tipo_doc == "Nota de Crédito":
            return "Notas de Credito"
        elif tipo_doc == "Resumo de Lote":
            return "Resumos de Lote"
        else:
            return "A Rever"
