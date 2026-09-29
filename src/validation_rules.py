import os
import re

class ValidationRules:
    """
    Motor de Validação de Regras de Negócio e Segurança de Dados.
    Aplica o duplo filtro de confiança, tratamento de duplicados e validação de lotes.
    Inclui normalização de fornecedores por NIF/NIPC com fallback por texto.
    """
    
    MANDATORY_FIELDS = ["numero_documento", "valor_total", "fornecedor", "data_documento"]

    # Aliases de texto para normalização de fornecedores sem NIF
    # Chave: padrão regex (case-insensitive) | Valor: nome canónico
    TEXT_ALIASES = {
        r"cooprofar|profar,\s*crl|oprofar": "Cooprofar",
        r"realc[oó]pia": "Realcópia",
        r"alliance\s*healthcare": "Alliance Healthcare",
        r"nos\s+comunica[cç][oõ]es|nos,\s*s\.?a": "NOS",
        r"utilm[eé]dica": "Utilmédica",
        r"gameiros": "Gameiros",
        r"abbott\s*laborat[oó]rios|abbott\s*lab": "Abbott Laboratórios",
        r"uriach": "Uriach",
        r"verlingue": "Verlingue",
        r"[aá]guas\s*do\s*interior": "Águas do Interior",
        r"nbc\s*consultores": "NBC Consultores",
    }

    @staticmethod
    def _clean_name(raw: str) -> str:
        """Limpa o nome do fornecedor removendo espaços extra e caracteres problemáticos."""
        if not raw:
            return ""
        return " ".join(str(raw).strip().split())

    @staticmethod
    def _clean_nif(raw_nif) -> str | None:
        """Valida e limpa um NIF — devolve string de 9 dígitos ou None."""
        if not raw_nif:
            return None
        digits = re.sub(r"\D", "", str(raw_nif))
        if len(digits) == 9:
            return digits
        return None

    @staticmethod
    def normalize_supplier(raw_name: str, raw_nif, supplier_map: dict) -> tuple:
        """
        Normaliza o nome do fornecedor usando NIF como identificador primário.

        Prioridade:
        1. NIF extraído + NIF conhecido no mapa → nome canónico do mapa
        2. NIF extraído + NIF novo (desconhecido) → regista no mapa, usa nome limpo do LLM
        3. Sem NIF → correspondência por texto nos aliases conhecidos
        4. Fallback final → usa nome raw do LLM limpo

        Retorna: (nome_normalizado: str, nif_limpo: str|None, supplier_map: dict)
        """
        nif = ValidationRules._clean_nif(raw_nif)
        nome_limpo = ValidationRules._clean_name(raw_name)

        # Prioridade 1: NIF conhecido no mapa
        if nif and nif in supplier_map:
            return supplier_map[nif], nif, supplier_map

        # Prioridade 2: NIF novo — regista e usa nome do LLM
        if nif and nif not in supplier_map:
            # Tenta primeiro encontrar por texto para usar nome canónico existente
            nome_por_texto = ValidationRules._match_by_text(nome_limpo)
            nome_canonico = nome_por_texto if nome_por_texto else nome_limpo
            supplier_map[nif] = nome_canonico
            print(f"  [Fornecedores] Novo NIF registado: {nif} → '{nome_canonico}'")
            return nome_canonico, nif, supplier_map

        # Prioridade 3: Sem NIF — correspondência por texto
        nome_por_texto = ValidationRules._match_by_text(nome_limpo)
        if nome_por_texto:
            return nome_por_texto, None, supplier_map

        # Prioridade 4: Fallback — usa nome raw do LLM
        return nome_limpo, None, supplier_map

    @staticmethod
    def _match_by_text(name: str) -> str | None:
        """Tenta encontrar o nome canónico a partir do nome raw usando aliases de texto."""
        if not name:
            return None
        name_lower = name.lower()
        for pattern, canonical in ValidationRules.TEXT_ALIASES.items():
            if re.search(pattern, name_lower):
                return canonical
        return None

    @staticmethod
    def validate_extraction(raw_data: dict, filename: str, supplier_map: dict = None) -> tuple:
        """
        Aplica as regras de validação cruzada e o duplo filtro de confiança do PRD.
        Inclui normalização de fornecedores por NIF.

        Retorna: (processed_data: dict, supplier_map: dict)
        """
        if supplier_map is None:
            supplier_map = {}

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

        # 4. Normalização do Fornecedor por NIF
        raw_name = processed.get("fornecedor", "")
        raw_nif = processed.get("nif_fornecedor")
        nome_normalizado, nif_limpo, supplier_map = ValidationRules.normalize_supplier(
            raw_name, raw_nif, supplier_map
        )

        # 5. Estado de Processamento e Nota
        if confianca_final == "baixa":
            nota = f"Processo manual necessário: {'; '.join(motivos)}" if motivos else "Processo manual necessário (baixa confiança)"
            categoria_pasta = "A Rever"
        else:
            nota = f"Lote associado: {processed.get('numero_lote_associado')}" if processed.get('numero_lote_associado') else ""
            categoria_pasta = ValidationRules.determine_folder_category(tipo_normalizado)

        processed.update({
            "tipo_documento": tipo_normalizado,
            "farmacia": farmacia_normalizada,
            "fornecedor": nome_normalizado,
            "nif_fornecedor": nif_limpo,
            "confianca": confianca_final.capitalize(),
            "motivo_baixa_confianca": "; ".join(motivos) if motivos else None,
            "categoria_pasta": categoria_pasta,
            "nota": nota
        })

        return processed, supplier_map

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
