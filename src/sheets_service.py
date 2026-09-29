import os
import json
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

class SheetsService:
    """
    Serviço de escrita nativa em Google Sheets via Google Sheets API v4.
    Requisito estrito do PRD: usa `values.append` para manter o ficheiro único e estável.
    Gera e atualiza automaticamente a aba 'Resumo Financeiro' (Dashboard dinâmico) e 'Log de Execuções'.
    """
    def __init__(self, spreadsheet_id: str, credentials_json_path: str = None, local_excel_path: str = "output/relatorio_faturas.xlsx", local_json_path: str = "data/documentos.json"):
        self.spreadsheet_id = spreadsheet_id
        self.local_excel_path = local_excel_path
        self.local_json_path = local_json_path
        self.service = None
        self.is_offline = True

        creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if creds_json:
            try:
                info = json.loads(creds_json)
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
                self.service = build('sheets', 'v4', credentials=creds)
                self.is_offline = False
                print("Google Sheets API v4 autenticada com sucesso (via ENV JSON).")
            except Exception as e:
                print(f"Erro ao autenticar GSheets com ENV JSON: {e}")

        elif credentials_json_path and os.path.exists(credentials_json_path):
            try:
                creds = service_account.Credentials.from_service_account_file(
                    credentials_json_path, scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
                self.service = build('sheets', 'v4', credentials=creds)
                self.is_offline = False
                print(f"Google Sheets API v4 autenticada com sucesso (via {credentials_json_path}).")
            except Exception as e:
                print(f"Erro ao autenticar GSheets com ficheiro {credentials_json_path}: {e}")

        if self.is_offline:
            print("Google Sheets API a funcionar em modo offline (Excel/JSON locais).")

    def ensure_sheet_tab_exists(self, tab_name: str, header_rows: list):
        """Garante que uma aba específica existe no Google Sheets; cria-a com cabeçalhos se necessário."""
        if self.is_offline or not self.service:
            return

        try:
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheets = spreadsheet.get('sheets', [])
            sheet_names = [s.get('properties', {}).get('title') for s in sheets]

            if tab_name not in sheet_names:
                print(f"  [GSheets API] Aba '{tab_name}' não encontrada. A criar nova aba...")
                batch_update_request = {
                    'requests': [
                        {
                            'addSheet': {
                                'properties': {
                                    'title': tab_name
                                }
                            }
                        }
                    ]
                }
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body=batch_update_request
                ).execute()

                if header_rows:
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"'{tab_name}'!A1",
                        valueInputOption="USER_ENTERED",
                        body={'values': header_rows}
                    ).execute()
                print(f"  [GSheets API] Aba '{tab_name}' criada com sucesso.")
        except Exception as e:
            print(f"Erro ao verificar/criar aba '{tab_name}': {e}")

    # ------------------------------------------------------------------
    # Aba Fornecedores — Mapa NIF → Nome Canónico
    # ------------------------------------------------------------------

    FORNECEDORES_INICIAIS = [
        ["500697370", "Cooprofar", "Distribuidor farmacêutico"],
        ["500856998", "Alliance Healthcare", "Distribuidor farmacêutico"],
        ["507280147", "NOS", "Telecomunicações"],
        ["500755030", "Realcópia", "Equipamento de escritório"],
        ["501177988", "Utilmédica", "Material médico"],
        ["503000626", "Gameiros", "Material clínico"],
        ["503041373", "Abbott Laboratórios", "Laboratório farmacêutico"],
        ["505028136", "Uriach", "Laboratório farmacêutico"],
        ["500138408", "Verlingue", "Corretora de seguros"],
        ["503268415", "Águas do Interior", "Água e consumíveis"],
        ["980341072", "NBC Consultores", "Consultoria"],
    ]

    def ensure_fornecedores_sheet_exists(self):
        """Garante que a aba 'Fornecedores' existe com cabeçalhos e NIFs iniciais."""
        if self.is_offline or not self.service:
            return

        try:
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheet_names = [s.get('properties', {}).get('title') for s in spreadsheet.get('sheets', [])]

            if 'Fornecedores' not in sheet_names:
                print("  [GSheets API] A criar aba 'Fornecedores' com mapa inicial de NIFs...")
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={'requests': [{'addSheet': {'properties': {'title': 'Fornecedores'}}}]}
                ).execute()

                header = [["NIF", "Nome Canónico", "Notas"]]
                rows = header + self.FORNECEDORES_INICIAIS
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Fornecedores'!A1",
                    valueInputOption="USER_ENTERED",
                    body={'values': rows}
                ).execute()
                print(f"  [GSheets API] Aba 'Fornecedores' criada com {len(self.FORNECEDORES_INICIAIS)} fornecedores iniciais.")
        except Exception as e:
            print(f"Erro ao garantir aba 'Fornecedores': {e}")

    def load_supplier_map(self) -> dict:
        """
        Lê a aba 'Fornecedores' e devolve um dicionário {nif: nome_canonico}.
        Garante que a aba existe primeiro.
        """
        self.ensure_fornecedores_sheet_exists()

        if self.is_offline or not self.service:
            # Fallback offline: usar mapa interno
            return {row[0]: row[1] for row in self.FORNECEDORES_INICIAIS if len(row) >= 2}

        try:
            res = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="'Fornecedores'!A2:B1000"
            ).execute()
            rows = res.get('values', [])
            supplier_map = {}
            for row in rows:
                if len(row) >= 2:
                    nif = str(row[0]).strip()
                    nome = str(row[1]).strip()
                    if nif and nome:
                        supplier_map[nif] = nome
            print(f"  [Fornecedores] Mapa carregado: {len(supplier_map)} fornecedores.")
            return supplier_map
        except Exception as e:
            print(f"Aviso ao ler aba 'Fornecedores': {e}")
            return {row[0]: row[1] for row in self.FORNECEDORES_INICIAIS if len(row) >= 2}

    def save_new_suppliers(self, supplier_map: dict):
        """
        Compara o supplier_map atual com a aba 'Fornecedores' e acrescenta
        quaisquer NIFs novos que não constem ainda na aba.
        """
        if self.is_offline or not self.service:
            return

        try:
            # Ler NIFs já existentes na aba
            res = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="'Fornecedores'!A2:A1000"
            ).execute()
            existing_nifs = set()
            for row in res.get('values', []):
                if row:
                    existing_nifs.add(str(row[0]).strip())

            # Filtrar apenas NIFs novos
            new_rows = []
            for nif, nome in supplier_map.items():
                if nif and str(nif) not in existing_nifs:
                    new_rows.append([str(nif), str(nome), "Descoberto automaticamente"])

            if new_rows:
                self.service.spreadsheets().values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Fornecedores'!A:C",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={'values': new_rows}
                ).execute()
                print(f"  [Fornecedores] {len(new_rows)} novo(s) fornecedor(es) acrescentado(s) à aba.")
        except Exception as e:
            print(f"Aviso ao guardar novos fornecedores: {e}")

    def ensure_resumo_sheet_exists(self):
        """Cria e atualiza a aba 'Resumo Financeiro' com fórmulas dinâmicas do Google Sheets."""
        default_suppliers = ["Cooprofar", "Alliance Healthcare", "NOS", "Realcópia", "Utilmédica"]
        suppliers = list(default_suppliers)
        
        if not self.is_offline and self.service:
            try:
                res = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Registo'!C2:C1000"
                ).execute()
                cols = res.get('values', [])
                for r in cols:
                    if r and len(r) > 0:
                        sup = str(r[0]).strip()
                        if sup and sup not in suppliers and sup.lower() != "fornecedor":
                            suppliers.append(sup)
            except Exception as e:
                print(f"Aviso ao ler fornecedores de Registo: {e}")

        rows = [
            ["DASHBOARD DE CONTROLO FINANCEIRO - FARMÁCIAS PILOTO"],
            [""],
            ["TOTAL FATURADO (€)", "TOTAL CREDITADO (€)", "TOTAL PAGO (€)", "TOTAL PENDENTE A PAGAR (€)", "DOCS A REVER (QTD)"],
            [
                '=SOMA.SE.S(Registo!G:G; Registo!B:B; "Fatura")',
                '=SOMA.SE.S(Registo!G:G; Registo!B:B; "Nota de Crédito")',
                '=SOMA.SE.S(Registo!G:G; Registo!I:I; "Pago")',
                '=SOMA.SE.S(Registo!G:G; Registo!B:B; "Fatura"; Registo!I:I; "Pendente") - SOMA.SE.S(Registo!G:G; Registo!B:B; "Nota de Crédito"; Registo!I:I; "Pendente")',
                '=CONTAR.SE(Registo!K:K; "Baixa")'
            ],
            [""],
            ["RESUMO POR FARMÁCIA"],
            ["Farmácia", "Total Faturado (€)", "Notas de Crédito (€)", "Total Pago (€)", "Pendente A Pagar (€)", "Qtd Pendentes"],
            [
                "Farmácia Baptista",
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Fatura")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Nota de Crédito")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!I:I; "Pago")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Fatura"; Registo!I:I; "Pendente") - SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Nota de Crédito"; Registo!I:I; "Pendente")',
                '=CONTAR.SE.S(Registo!D:D; "Farmácia Baptista"; Registo!I:I; "Pendente")'
            ],
            [
                "Farmácia Campeã",
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Fatura")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Nota de Crédito")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!I:I; "Pago")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Fatura"; Registo!I:I; "Pendente") - SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Nota de Crédito"; Registo!I:I; "Pendente")',
                '=CONTAR.SE.S(Registo!D:D; "Farmácia Campeã"; Registo!I:I; "Pendente")'
            ],
            [
                "Indeterminado / A Rever",
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!B:B; "Fatura")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!B:B; "Nota de Crédito")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!I:I; "Pago")',
                '=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!B:B; "Fatura"; Registo!I:I; "Pendente")',
                '=CONTAR.SE.S(Registo!D:D; "Indeterminado"; Registo!I:I; "Pendente")'
            ],
            [""],
            ["BALANÇO POR FORNECEDOR"],
            ["Fornecedor", "Faturas (€)", "Créditos (€)", "Já Pago (€)", "Pendente Atual (€)"]
        ]

        start_row = 14
        for idx, sup in enumerate(suppliers):
            row_num = start_row + idx
            rows.append([
                sup,
                f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!B:B; "Fatura")',
                f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!B:B; "Nota de Crédito")',
                f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!I:I; "Pago")',
                f'=B{row_num}-C{row_num}-D{row_num}'
            ])
        self.ensure_sheet_tab_exists("Resumo Financeiro", rows)
        
        # Limpar fórmulas antigas com erro e reescrever fórmulas atualizadas
        if not self.is_offline and self.service:
            try:
                self.service.spreadsheets().values().clear(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Resumo Financeiro'!A1:Z50"
                ).execute()

                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Resumo Financeiro'!A1",
                    valueInputOption="USER_ENTERED",
                    body={'values': rows}
                ).execute()
            except Exception as e:
                print(f"Aviso ao atualizar fórmulas da aba Resumo Financeiro: {e}")

    def ensure_log_sheet_exists(self):
        header = [[
            "Data/Hora Execução (UTC)",
            "Total Processados",
            "Confiança Alta",
            "Confiança Média",
            "Confiança Baixa (A Rever)",
            "Total Pendente (€)",
            "Origem Instruções",
            "Notas / Resumo"
        ]]
        self.ensure_sheet_tab_exists("Log de Execuções", header)

    def ensure_registo_sheet_exists(self):
        header = [
            "Nº Documento",
            "Tipo",
            "Fornecedor",
            "Farmácia",
            "Data",
            "Data Vencimento",
            "Valor (€)",
            "Nº Lote Associado",
            "Estado Pagamento",
            "Data Pagamento",
            "Confiança",
            "Ficheiro",
            "Nota",
            "NIF Fornecedor"
        ]
        self.ensure_sheet_tab_exists("Registo", [header])
        
        # Garantir que a linha 1 tem os 14 cabeçalhos e migrar registos existentes se necessário
        if not self.is_offline and self.service:
            try:
                res = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Registo'!A1:Z1000"
                ).execute()
                rows = res.get('values', [])
                
                if rows and len(rows) > 0:
                    old_headers = [str(c).strip() for c in rows[0]]
                    has_vencimento = any("vencimento" in h.lower() for h in old_headers)
                    has_nif = any("nif" in h.lower() for h in old_headers)
                    
                    if not has_vencimento:
                        # Migração: 12 → 14 colunas (adiciona Data Vencimento + NIF Fornecedor)
                        print("  [GSheets API] A migrar aba 'Registo' para 14 colunas (Data Vencimento + NIF Fornecedor)...")
                        new_rows = [header]
                        
                        header_map = {}
                        for idx, h in enumerate(old_headers):
                            hl = h.lower()
                            if ("doc" in hl or "nº" in hl or "numero" in hl) and "lote" not in hl:
                                header_map["Nº Documento"] = idx
                            if "tipo" in hl: header_map["Tipo"] = idx
                            if "fornecedor" in hl: header_map["Fornecedor"] = idx
                            if "farmá" in hl or "farmacia" in hl: header_map["Farmácia"] = idx
                            if "data" in hl and "vencimento" not in hl and "pagamento" not in hl: header_map["Data"] = idx
                            if "valor" in hl: header_map["Valor (€)"] = idx
                            if "lote" in hl: header_map["Nº Lote Associado"] = idx
                            if "estado" in hl or ("pagamento" in hl and "data" not in hl): header_map["Estado Pagamento"] = idx
                            if "data" in hl and "pagamento" in hl: header_map["Data Pagamento"] = idx
                            if "confian" in hl or "confia" in hl: header_map["Confiança"] = idx
                            if "ficheiro" in hl or "link" in hl: header_map["Ficheiro"] = idx
                            if "nota" in hl or "observa" in hl: header_map["Nota"] = idx
                        
                        for r in rows[1:]:
                            new_r = []
                            for target in header:
                                if target == "Data Vencimento":
                                    data_i = header_map.get("Data")
                                    val = r[data_i] if data_i is not None and data_i < len(r) else ""
                                    new_r.append(val)
                                elif target == "NIF Fornecedor":
                                    new_r.append("")  # vazio para registos antigos
                                else:
                                    i = header_map.get(target)
                                    val = r[i] if i is not None and i < len(r) else ""
                                    new_r.append(val)
                            new_rows.append(new_r)
                        
                        self.service.spreadsheets().values().clear(
                            spreadsheetId=self.spreadsheet_id,
                            range="'Registo'!A1:Z1000"
                        ).execute()
                        
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range="'Registo'!A1",
                            valueInputOption="USER_ENTERED",
                            body={'values': new_rows}
                        ).execute()
                        print("  [GSheets API] Aba 'Registo' migrada com sucesso para 14 colunas.")
                    elif not has_nif:
                        # Migração: 13 → 14 colunas (apenas adiciona NIF Fornecedor na col N)
                        print("  [GSheets API] A adicionar coluna 'NIF Fornecedor' (col N) à aba 'Registo'...")
                        new_rows = [header]
                        for r in rows[1:]:
                            new_r = list(r)
                            while len(new_r) < 13:
                                new_r.append("")
                            new_r.append("")  # NIF Fornecedor vazio para registos antigos
                            new_rows.append(new_r)
                        
                        self.service.spreadsheets().values().clear(
                            spreadsheetId=self.spreadsheet_id,
                            range="'Registo'!A1:Z1000"
                        ).execute()
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range="'Registo'!A1",
                            valueInputOption="USER_ENTERED",
                            body={'values': new_rows}
                        ).execute()
                        print("  [GSheets API] Coluna 'NIF Fornecedor' adicionada com sucesso.")
                    else:
                        # Apenas garantir que o cabeçalho está correto
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range="'Registo'!A1:N1",
                            valueInputOption="USER_ENTERED",
                            body={'values': [header]}
                        ).execute()
            except Exception as e:
                print(f"Aviso ao atualizar cabeçalho da aba Registo: {e}")

    def get_sheet_headers(self, tab_name: str) -> list:
        """Obtém os nomes de colunas do cabeçalho da aba existente."""
        if self.is_offline or not self.service:
            return []
        try:
            res = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab_name}'!1:1"
            ).execute()
            rows = res.get('values', [])
            if rows and len(rows) > 0:
                return [str(c).strip() for c in rows[0]]
        except Exception as e:
            print(f"Aviso ao ler cabeçalho de '{tab_name}': {e}")
        return []

    def append_execution_log(self, log_data: dict) -> bool:
        """Regista uma linha de auditoria na aba 'Log de Execuções'."""
        self.ensure_log_sheet_exists()
        self.ensure_resumo_sheet_exists()

        row_values = [
            str(log_data.get("timestamp_utc") or ""),
            int(log_data.get("total_processados") or 0),
            int(log_data.get("qtd_alta") or 0),
            int(log_data.get("qtd_media") or 0),
            int(log_data.get("qtd_baixa") or 0),
            float(log_data.get("total_pendente") or 0.0),
            str(log_data.get("origem_instrucoes") or "Google Docs (_Config Agente)"),
            str(log_data.get("resumo_notas") or "")
        ]

        if self.is_offline or not self.service:
            print(f"  [Local Fallback] Registo de Execução em log local: {row_values}")
            return True

        try:
            body = {'values': [row_values]}
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="'Log de Execuções'!A:H",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body
            ).execute()
            print("  [GSheets API] Linha de log de execução registada na aba 'Log de Execuções'.")
            return True
        except Exception as e:
            print(f"Erro ao registar log de execução no GSheets API: {e}")
            return False

    def append_document_row(self, doc_data: dict, drive_url: str) -> bool:
        """
        Adiciona uma nova linha de documento no registo principal alinhando dinamicamente com os cabeçalhos reais.
        """
        self.ensure_registo_sheet_exists()
        self.ensure_resumo_sheet_exists()

        if doc_data.get("tipo_documento") == "Resumo de Lote" and doc_data.get("confianca") != "Baixa":
            print("  [Opção B PRD] Resumo de Lote registado no Supabase; omitida linha financeira no Sheets.")
            return True

        existing_headers = self.get_sheet_headers("Registo")

        data_venc = str(doc_data.get("data_vencimento") or doc_data.get("data_documento") or "")
        nif_fornecedor = str(doc_data.get("nif_fornecedor") or "")

        mapping = {
            "Nº Documento": str(doc_data.get("numero_documento") or ""),
            "Tipo": str(doc_data.get("tipo_documento") or "A Rever"),
            "Fornecedor": str(doc_data.get("fornecedor") or ""),
            "Farmácia": str(doc_data.get("farmacia") or "Indeterminado"),
            "Data": str(doc_data.get("data_documento") or ""),
            "Data Vencimento": data_venc,
            "Valor (€)": float(doc_data.get("valor_total") or 0.0) if doc_data.get("valor_total") is not None else 0.0,
            "Nº Lote Associado": str(doc_data.get("numero_lote_associado") or doc_data.get("numero_lote") or ""),
            "Estado Pagamento": str(doc_data.get("estado_pagamento") or "Pendente"),
            "Data Pagamento": str(doc_data.get("data_pagamento") or ""),
            "Confiança": str(doc_data.get("confianca") or "Baixa"),
            "Ficheiro": str(drive_url or ""),
            "Ficheiro (link Drive)": str(drive_url or ""),
            "Nota": str(doc_data.get("nota") or ""),
            "NIF Fornecedor": nif_fornecedor,
        }

        if existing_headers:
            row_values = []
            for col in existing_headers:
                col_clean = col.strip()
                if "fatura" in col_clean.lower() or "ficheiro" in col_clean.lower() or "link" in col_clean.lower():
                    row_values.append(str(drive_url or ""))
                elif "nif" in col_clean.lower():
                    row_values.append(nif_fornecedor)
                elif "lote" in col_clean.lower():
                    row_values.append(str(doc_data.get("numero_lote_associado") or doc_data.get("numero_lote") or ""))
                elif "vencimento" in col_clean.lower() or "limite" in col_clean.lower():
                    row_values.append(data_venc)
                elif "confiança" in col_clean.lower() or "confianca" in col_clean.lower():
                    row_values.append(str(doc_data.get("confianca") or "Baixa"))
                elif "nota" in col_clean.lower() or "observa" in col_clean.lower():
                    row_values.append(str(doc_data.get("nota") or ""))
                else:
                    row_values.append(mapping.get(col_clean, ""))
        else:
            row_values = [
                str(doc_data.get("numero_documento") or ""),
                str(doc_data.get("tipo_documento") or "A Rever"),
                str(doc_data.get("fornecedor") or ""),
                str(doc_data.get("farmacia") or "Indeterminado"),
                str(doc_data.get("data_documento") or ""),
                data_venc,
                float(doc_data.get("valor_total") or 0.0) if doc_data.get("valor_total") is not None else 0.0,
                str(doc_data.get("numero_lote_associado") or doc_data.get("numero_lote") or ""),
                str(doc_data.get("estado_pagamento") or "Pendente"),
                str(doc_data.get("data_pagamento") or ""),
                str(doc_data.get("confianca") or "Baixa"),
                str(drive_url or ""),
                str(doc_data.get("nota") or "")
            ]

        if self.is_offline:
            return self._append_local(doc_data, row_values, drive_url)

        try:
            body = {'values': [row_values]}
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="'Registo'!A:Z",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body
            ).execute()
            print(f"  [GSheets API] Linha do documento {doc_data.get('numero_documento')} anexada com sucesso.")
            return True
        except Exception as e:
            print(f"Erro ao anexar linha no GSheets API: {e}. A guardar localmente...")
            return self._append_local(doc_data, row_values, drive_url)

    def _append_local(self, doc_data: dict, row_values: list, drive_url: str) -> bool:
        """Guarda localmente em JSON e Excel Único para fallback offline."""
        os.makedirs(os.path.dirname(self.local_json_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.local_excel_path), exist_ok=True)

        records = []
        if os.path.exists(self.local_json_path):
            try:
                with open(self.local_json_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except Exception:
                records = []

        record_entry = dict(doc_data)
        record_entry["drive_url"] = drive_url
        records.append(record_entry)

        with open(self.local_json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        table_rows = []
        for r in records:
            if r.get("tipo_documento") == "Resumo de Lote" and r.get("confianca") != "Baixa":
                continue
            table_rows.append({
                "Nº Documento": r.get("numero_documento", ""),
                "Tipo": r.get("tipo_documento", ""),
                "Fornecedor": r.get("fornecedor", ""),
                "Farmácia": r.get("farmacia", ""),
                "Data": r.get("data_documento", ""),
                "Data Vencimento": r.get("data_vencimento", r.get("data_documento", "")),
                "Valor (€)": r.get("valor_total", 0.0),
                "Nº Lote Associado": r.get("numero_lote_associado", r.get("numero_lote", "")),
                "Estado Pagamento": r.get("estado_pagamento", "Pendente"),
                "Data Pagamento": r.get("data_pagamento", ""),
                "Confiança": r.get("confianca", "Baixa"),
                "Ficheiro": r.get("drive_url", ""),
                "Nota": r.get("nota", "")
            })

        try:
            df = pd.DataFrame(table_rows)
            with pd.ExcelWriter(self.local_excel_path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Registo", index=False)
            print(f"  [Local Fallback] Documento registado no Excel local em: {self.local_excel_path}")
        except Exception as e:
            print(f"  [Aviso] Não foi possível atualizar o Excel local ({e}). Registado em JSON.")
        return True
