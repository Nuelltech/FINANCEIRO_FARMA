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

    def ensure_resumo_sheet_exists(self):
        """Cria e atualiza a aba 'Resumo Financeiro' com fórmulas dinâmicas do Google Sheets."""
        rows = [
            ["DASHBOARD DE CONTROLO FINANCEIRO - FARMÁCIAS PILOTO"],
            [""],
            ["TOTAL FATURADO (€)", "TOTAL CREDITADO (€)", "TOTAL PAGO (€)", "TOTAL PENDENTE A PAGAR (€)", "DOCS A REVER (QTD)"],
            [
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!B:B; "Fatura")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!B:B; "Nota de Crédito")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!I:I; "Pago")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!B:B; "Fatura"; \'Registo\'!I:I; "Pendente") - SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!B:B; "Nota de Crédito"; \'Registo\'!I:I; "Pendente")',
                '=CONTAR.SE(\'Registo\'!K:K; "Baixa")'
            ],
            [""],
            ["RESUMO POR FARMÁCIA"],
            ["Farmácia", "Total Faturado (€)", "Notas de Crédito (€)", "Total Pago (€)", "Pendente A Pagar (€)", "Qtd Pendentes"],
            [
                "Farmácia Baptista",
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Baptista"; \'Registo\'!B:B; "Fatura")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Baptista"; \'Registo\'!B:B; "Nota de Crédito")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Baptista"; \'Registo\'!I:I; "Pago")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Baptista"; \'Registo\'!B:B; "Fatura"; \'Registo\'!I:I; "Pendente") - SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Baptista"; \'Registo\'!B:B; "Nota de Crédito"; \'Registo\'!I:I; "Pendente")',
                '=CONTAR.SE.S(\'Registo\'!D:D; "Farmácia Baptista"; \'Registo\'!I:I; "Pendente")'
            ],
            [
                "Farmácia Campeã",
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Campeã"; \'Registo\'!B:B; "Fatura")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Campeã"; \'Registo\'!B:B; "Nota de Crédito")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Campeã"; \'Registo\'!I:I; "Pago")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Campeã"; \'Registo\'!B:B; "Fatura"; \'Registo\'!I:I; "Pendente") - SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Farmácia Campeã"; \'Registo\'!B:B; "Nota de Crédito"; \'Registo\'!I:I; "Pendente")',
                '=CONTAR.SE.S(\'Registo\'!D:D; "Farmácia Campeã"; \'Registo\'!I:I; "Pendente")'
            ],
            [
                "Indeterminado / A Rever",
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Indeterminado"; \'Registo\'!B:B; "Fatura")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Indeterminado"; \'Registo\'!B:B; "Nota de Crédito")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Indeterminado"; \'Registo\'!I:I; "Pago")',
                '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!D:D; "Indeterminado"; \'Registo\'!B:B; "Fatura"; \'Registo\'!I:I; "Pendente")',
                '=CONTAR.SE.S(\'Registo\'!D:D; "Indeterminado"; \'Registo\'!I:I; "Pendente")'
            ],
            [""],
            ["BALANÇO POR FORNECEDOR"],
            ["Fornecedor", "Faturas (€)", "Créditos (€)", "Já Pago (€)", "Pendente Atual (€)"],
            ["Cooprofar", '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Cooprofar"; \'Registo\'!B:B; "Fatura")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Cooprofar"; \'Registo\'!B:B; "Nota de Crédito")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Cooprofar"; \'Registo\'!I:I; "Pago")', '=B14-C14-D14'],
            ["Alliance Healthcare", '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Alliance Healthcare"; \'Registo\'!B:B; "Fatura")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Alliance Healthcare"; \'Registo\'!B:B; "Nota de Crédito")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Alliance Healthcare"; \'Registo\'!I:I; "Pago")', '=B15-C15-D15'],
            ["NOS", '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "NOS"; \'Registo\'!B:B; "Fatura")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "NOS"; \'Registo\'!B:B; "Nota de Crédito")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "NOS"; \'Registo\'!I:I; "Pago")', '=B16-C16-D16'],
            ["Realcópia", '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Realcópia"; \'Registo\'!B:B; "Fatura")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Realcópia"; \'Registo\'!B:B; "Nota de Crédito")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Realcópia"; \'Registo\'!I:I; "Pago")', '=B17-C17-D17'],
            ["Utilmédica", '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Utilmédica"; \'Registo\'!B:B; "Fatura")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Utilmédica"; \'Registo\'!B:B; "Nota de Crédito")', '=SOMAS.SE.S(\'Registo\'!G:G; \'Registo\'!C:C; "Utilmédica"; \'Registo\'!I:I; "Pago")', '=B18-C18-D18']
        ]
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
            "Nota"
        ]
        self.ensure_sheet_tab_exists("Registo", [header])
        
        # Garantir que a linha 1 da aba Registo tem os 13 cabeçalhos e migrar registos existentes se necessário
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
                    
                    if not has_vencimento:
                        print("  [GSheets API] A migrar aba 'Registo' para incluir coluna 'Data Vencimento'...")
                        new_rows = [header]
                        
                        header_map = {}
                        for idx, h in enumerate(old_headers):
                            hl = h.lower()
                            if "doc" in hl or "nº" in hl or "numero" in hl:
                                if "lote" not in hl: header_map["Nº Documento"] = idx
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
                        print("  [GSheets API] Aba 'Registo' migrada com sucesso para 13 colunas.")
                    else:
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range="'Registo'!A1:M1",
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
            "Nota": str(doc_data.get("nota") or "")
        }

        if existing_headers:
            row_values = []
            for col in existing_headers:
                col_clean = col.strip()
                if "fatura" in col_clean.lower() or "ficheiro" in col_clean.lower() or "link" in col_clean.lower():
                    row_values.append(str(drive_url or ""))
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
