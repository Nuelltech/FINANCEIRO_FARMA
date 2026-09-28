import os
import json
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

class SheetsService:
    """
    Serviço de escrita nativa em Google Sheets via Google Sheets API v4.
    Requisito estrito do PRD: usa `values.append` para manter o ficheiro único e estável.
    Suporta o registo auditável na aba `Log de Execuções` (gerada automaticamente se não existir).
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

    def ensure_sheet_tab_exists(self, tab_name: str, header_row: list):
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

                if header_row:
                    self.service.spreadsheets().values().append(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"'{tab_name}'!A1",
                        valueInputOption="USER_ENTERED",
                        body={'values': [header_row]}
                    ).execute()
                print(f"  [GSheets API] Aba '{tab_name}' criada com cabeçalhos com sucesso.")
        except Exception as e:
            print(f"Erro ao verificar/criar aba '{tab_name}': {e}")

    def ensure_log_sheet_exists(self):
        header = [
            "Data/Hora Execução (UTC)",
            "Total Processados",
            "Confiança Alta",
            "Confiança Média",
            "Confiança Baixa (A Rever)",
            "Total Pendente (€)",
            "Origem Instruções",
            "Notas / Resumo"
        ]
        self.ensure_sheet_tab_exists("Log de Execuções", header)

    def ensure_registo_sheet_exists(self):
        header = [
            "Nº Documento",
            "Tipo",
            "Fornecedor",
            "Farmácia",
            "Data",
            "Valor (€)",
            "Nº Lote Associado",
            "Estado Pagamento",
            "Data Pagamento",
            "Confiança",
            "Ficheiro (link Drive)",
            "Nota"
        ]
        self.ensure_sheet_tab_exists("Registo", header)

    def append_execution_log(self, log_data: dict) -> bool:
        """
        Regista uma linha de auditoria na aba 'Log de Execuções' no final da execução.
        """
        self.ensure_log_sheet_exists()

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
        Adiciona uma nova linha de documento no registo principal sem nunca recriar a folha.
        Colunas:
        1. Nº Documento | 2. Tipo | 3. Fornecedor | 4. Farmácia | 5. Data | 6. Valor (€) | 7. Nº Lote Associado | 8. Estado Pagamento | 9. Data Pagamento | 10. Confiança | 11. Ficheiro (link Drive) | 12. Nota
        """
        self.ensure_registo_sheet_exists()
        if doc_data.get("tipo_documento") == "Resumo de Lote" and doc_data.get("confianca") != "Baixa":
            print("  [Opção B PRD] Resumo de Lote registado no Supabase; omitida linha financeira no Sheets.")
            return True

        row_values = [
            str(doc_data.get("numero_documento") or ""),
            str(doc_data.get("tipo_documento") or "A Rever"),
            str(doc_data.get("fornecedor") or ""),
            str(doc_data.get("farmacia") or "Indeterminado"),
            str(doc_data.get("data_documento") or ""),
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
                range="'Registo'!A:L",
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
                "Valor (€)": r.get("valor_total", 0.0),
                "Nº Lote Associado": r.get("numero_lote_associado", r.get("numero_lote", "")),
                "Estado Pagamento": r.get("estado_pagamento", "Pendente"),
                "Data Pagamento": r.get("data_pagamento", ""),
                "Confiança": r.get("confianca", "Baixa"),
                "Ficheiro (link Drive)": r.get("drive_url", ""),
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
