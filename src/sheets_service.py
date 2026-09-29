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

    FORNECEDORES_INICIAIS = []

    def ensure_fornecedores_sheet_exists(self):
        """Garante que a aba 'Fornecedores' existe com cabeçalhos."""
        if self.is_offline or not self.service:
            return

        try:
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheet_names = [s.get('properties', {}).get('title') for s in spreadsheet.get('sheets', [])]

            if 'Fornecedores' not in sheet_names:
                print("  [GSheets API] A criar aba 'Fornecedores'...")
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={'requests': [{'addSheet': {'properties': {'title': 'Fornecedores'}}}]}
                ).execute()

                header = [["NIF", "Nome Canónico", "Notas"]]
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Fornecedores'!A1",
                    valueInputOption="USER_ENTERED",
                    body={'values': header}
                ).execute()
                print("  [GSheets API] Aba 'Fornecedores' criada.")
        except Exception as e:
            print(f"Erro ao garantir aba 'Fornecedores': {e}")

    def load_supplier_map(self) -> dict:
        """
        Lê a aba 'Fornecedores' e devolve um dicionário {nif: nome_canonico}.
        Garante que a aba existe primeiro.
        """
        self.ensure_fornecedores_sheet_exists()

        if self.is_offline or not self.service:
            return {}

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
            print(f"  [Fornecedores] Mapa carregado: {len(supplier_map)} fornecedores registados.")
            return supplier_map
        except Exception as e:
            print(f"Aviso ao ler aba 'Fornecedores': {e}")
            return {}

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
        """
        Gere a aba 'Resumo Financeiro' de forma não destrutiva:
        - Se a aba NÃO existir → cria o template completo com fórmulas e filtro de datas.
        - Se a aba JÁ EXISTIR → não toca na estrutura; apenas adiciona linhas
          de fornecedores novos no fundo da tabela 'Balanço por Fornecedor'.
        As fórmulas SOMA.SE.S leem o Registo dinamicamente com suporte a filtro de intervalo de datas (B2 e D2).
        """
        if self.is_offline or not self.service:
            return

        # Verificar se a aba já existe
        try:
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheet_names = [s.get('properties', {}).get('title') for s in spreadsheet.get('sheets', [])]
            tab_exists = 'Resumo Financeiro' in sheet_names
        except Exception as e:
            print(f"Aviso ao verificar aba 'Resumo Financeiro': {e}")
            return

        if not tab_exists:
            # ── Primeira vez: criar o template completo ──────────────────────
            print("  [GSheets API] Aba 'Resumo Financeiro' não existe. A criar template com filtro de datas...")
            self._create_resumo_template()
        else:
            # ── Aba já existe: apenas adicionar novos fornecedores ────────────
            self._append_new_suppliers_to_resumo()

    def _create_resumo_template(self):
        """Cria o template completo da aba 'Resumo Financeiro' com filtro de datas (B2 e D2)."""
        # Descobrir APENAS fornecedores reais que já constem no Registo
        suppliers = []
        try:
            res = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="'Registo'!C2:C1000"
            ).execute()
            for r in res.get('values', []):
                if r and r[0].strip() and r[0].strip() not in suppliers and r[0].strip().lower() != "fornecedor":
                    suppliers.append(r[0].strip())
        except Exception:
            pass

        # Expressão de filtro de datas (célula B2 = Início, D2 = Fim; se vazias, considera todo o histórico)
        dt_filter = 'Registo!E:E; ">=" & SE($B$2=""; "1900-01-01"; $B$2); Registo!E:E; "<=" & SE($D$2=""; "2099-12-31"; $D$2)'

        rows = [
            ["DASHBOARD DE CONTROLO FINANCEIRO - FARMÁCIAS PILOTO"],
            ["Data Início (AAAA-MM-DD):", "", "Data Fim (AAAA-MM-DD):", "", "(Deixe em branco para ver todo o período)"],
            ["TOTAL FATURADO (€)", "TOTAL CREDITADO (€)", "TOTAL PAGO (€)", "TOTAL PENDENTE A PAGAR (€)", "DOCS A REVER (QTD)"],
            [
                f'=SOMA.SE.S(Registo!G:G; Registo!B:B; "Fatura"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!B:B; "Nota de Crédito"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!I:I; "Pago"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!B:B; "Fatura"; Registo!I:I; "Pendente"; {dt_filter}) - SOMA.SE.S(Registo!G:G; Registo!B:B; "Nota de Crédito"; Registo!I:I; "Pendente"; {dt_filter})',
                '=CONTAR.SE(Registo!K:K; "Baixa")'
            ],
            [""],
            ["RESUMO POR FARMÁCIA"],
            ["Farmácia", "Total Faturado (€)", "Notas de Crédito (€)", "Total Pago (€)", "Pendente A Pagar (€)", "Qtd Pendentes"],
            [
                "Farmácia Baptista",
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Fatura"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Nota de Crédito"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!I:I; "Pago"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Fatura"; Registo!I:I; "Pendente"; {dt_filter}) - SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Baptista"; Registo!B:B; "Nota de Crédito"; Registo!I:I; "Pendente"; {dt_filter})',
                f'=CONTAR.SE.S(Registo!D:D; "Farmácia Baptista"; Registo!I:I; "Pendente"; {dt_filter})'
            ],
            [
                "Farmácia Campeã",
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Fatura"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Nota de Crédito"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!I:I; "Pago"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Fatura"; Registo!I:I; "Pendente"; {dt_filter}) - SOMA.SE.S(Registo!G:G; Registo!D:D; "Farmácia Campeã"; Registo!B:B; "Nota de Crédito"; Registo!I:I; "Pendente"; {dt_filter})',
                f'=CONTAR.SE.S(Registo!D:D; "Farmácia Campeã"; Registo!I:I; "Pendente"; {dt_filter})'
            ],
            [
                "Indeterminado / A Rever",
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!B:B; "Fatura"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!B:B; "Nota de Crédito"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!I:I; "Pago"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!D:D; "Indeterminado"; Registo!B:B; "Fatura"; Registo!I:I; "Pendente"; {dt_filter})',
                f'=CONTAR.SE.S(Registo!D:D; "Indeterminado"; Registo!I:I; "Pendente"; {dt_filter})'
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
                f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!B:B; "Fatura"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!B:B; "Nota de Crédito"; {dt_filter})',
                f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!I:I; "Pago"; {dt_filter})',
                f'=B{row_num}-C{row_num}-D{row_num}'
            ])

        try:
            # Criar a aba
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': [{'addSheet': {'properties': {'title': 'Resumo Financeiro'}}}]}
            ).execute()
            # Escrever o template
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range="'Resumo Financeiro'!A1",
                valueInputOption="USER_ENTERED",
                body={'values': rows}
            ).execute()
            print(f"  [GSheets API] Template 'Resumo Financeiro' criado com {len(suppliers)} fornecedor(es) e filtro de datas.")
        except Exception as e:
            print(f"Erro ao criar template 'Resumo Financeiro': {e}")

    def _append_new_suppliers_to_resumo(self):
        """
        Adiciona linhas de fornecedores NOVOS no fundo da tabela 'Balanço por Fornecedor'
        com suporte ao filtro de datas, sem tocar no que já existe.
        """
        try:
            # Ler nomes de fornecedores já presentes na tabela (coluna A, a partir da linha 14)
            res = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="'Resumo Financeiro'!A14:A200"
            ).execute()
            existing_in_resumo = set()
            last_row = 13  # linha anterior à primeira linha de fornecedores
            for i, row in enumerate(res.get('values', []), start=14):
                if row and str(row[0]).strip():
                    existing_in_resumo.add(str(row[0]).strip())
                    last_row = i

            # Ler fornecedores actuais do Registo
            res2 = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="'Registo'!C2:C1000"
            ).execute()
            registo_suppliers = set()
            for r in res2.get('values', []):
                if r and r[0].strip() and r[0].strip().lower() != "fornecedor":
                    registo_suppliers.add(r[0].strip())

            # Descobrir fornecedores que ainda não têm linha no Resumo Financeiro
            novos = [s for s in registo_suppliers if s not in existing_in_resumo]
            if not novos:
                return  # Nada a fazer — template está completo

            dt_filter = 'Registo!E:E; ">=" & SE($B$2=""; "1900-01-01"; $B$2); Registo!E:E; "<=" & SE($D$2=""; "2099-12-31"; $D$2)'

            # Adicionar linhas para fornecedores novos
            new_rows = []
            for idx, sup in enumerate(novos):
                row_num = last_row + 1 + idx
                new_rows.append([
                    sup,
                    f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!B:B; "Fatura"; {dt_filter})',
                    f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!B:B; "Nota de Crédito"; {dt_filter})',
                    f'=SOMA.SE.S(Registo!G:G; Registo!C:C; A{row_num}; Registo!I:I; "Pago"; {dt_filter})',
                    f'=B{row_num}-C{row_num}-D{row_num}'
                ])

            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="'Resumo Financeiro'!A:E",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={'values': new_rows}
            ).execute()
            print(f"  [GSheets API] {len(new_rows)} novo(s) fornecedor(es) adicionado(s) ao 'Resumo Financeiro'.")
        except Exception as e:
            print(f"Aviso ao actualizar fornecedores no 'Resumo Financeiro': {e}")




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
            "NIF Fornecedor",
            "Reprocessar"
        ]
        self.ensure_sheet_tab_exists("Registo", [header])
        
        # Garantir que a linha 1 tem os 15 cabeçalhos e migrar registos existentes se necessário
        if not self.is_offline and self.service:
            try:
                res = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range="'Registo'!A1:Z1000"
                ).execute()
                rows = res.get('values', [])
                
                if rows and len(rows) > 0:
                    old_headers = [str(c).strip() for c in rows[0]]
                    has_reprocessar = any("reprocessar" in h.lower() for h in old_headers)
                    has_nif = any("nif" in h.lower() for h in old_headers)
                    has_vencimento = any("vencimento" in h.lower() for h in old_headers)
                    
                    if not has_reprocessar or not has_nif or not has_vencimento or len(old_headers) < len(header):
                        print("  [GSheets API] A atualizar cabeçalhos da aba 'Registo' para 15 colunas...")
                        header_map = {}
                        for idx, h in enumerate(old_headers):
                            hl = h.lower()
                            if ("doc" in hl or "nº" in hl or "numero" in hl) and "lote" not in hl:
                                header_map["Nº Documento"] = idx
                            elif "tipo" in hl: header_map["Tipo"] = idx
                            elif "fornecedor" in hl and "nif" not in hl: header_map["Fornecedor"] = idx
                            elif "farmá" in hl or "farmacia" in hl: header_map["Farmácia"] = idx
                            elif "data" in hl and "vencimento" not in hl and "pagamento" not in hl: header_map["Data"] = idx
                            elif "vencimento" in hl: header_map["Data Vencimento"] = idx
                            elif "valor" in hl: header_map["Valor (€)"] = idx
                            elif "lote" in hl: header_map["Nº Lote Associado"] = idx
                            elif "estado" in hl or ("pagamento" in hl and "data" not in hl): header_map["Estado Pagamento"] = idx
                            elif "data" in hl and "pagamento" in hl: header_map["Data Pagamento"] = idx
                            elif "confian" in hl or "confia" in hl: header_map["Confiança"] = idx
                            elif "ficheiro" in hl or "link" in hl: header_map["Ficheiro"] = idx
                            elif "nota" in hl or "observa" in hl: header_map["Nota"] = idx
                            elif "nif" in hl: header_map["NIF Fornecedor"] = idx
                            elif "reprocessar" in hl: header_map["Reprocessar"] = idx
                        
                        new_rows = [header]
                        for r in rows[1:]:
                            new_r = []
                            for target in header:
                                idx = header_map.get(target)
                                val = r[idx] if idx is not None and idx < len(r) else ""
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
                        print("  [GSheets API] Aba 'Registo' atualizada com sucesso para 15 colunas.")
                    else:
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range="'Registo'!A1:O1",
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

    def get_rows_to_reprocess(self) -> list:
        """
        Lê a aba 'Registo' e devolve linhas onde a coluna 'Reprocessar' está marcada como 'Sim' / 'sim' / '1' / 'true'.
        """
        if self.is_offline or not self.service:
            return []
        try:
            res = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="'Registo'!A1:O1000"
            ).execute()
            rows = res.get('values', [])
            if not rows or len(rows) <= 1:
                return []

            headers = [str(c).strip().lower() for c in rows[0]]
            
            # Mapear índices
            def get_idx(patterns):
                for p in patterns:
                    for i, h in enumerate(headers):
                        if p in h:
                            return i
                return None

            idx_doc = get_idx(["doc", "nº", "numero"])
            idx_tipo = get_idx(["tipo"])
            idx_forn = get_idx(["fornecedor"])
            idx_farm = get_idx(["farmá", "farmacia"])
            idx_data = get_idx(["data"])
            idx_venc = get_idx(["vencimento"])
            idx_val = get_idx(["valor"])
            idx_lote = get_idx(["lote"])
            idx_file = get_idx(["ficheiro", "link"])
            idx_nota = get_idx(["nota"])
            idx_nif = get_idx(["nif"])
            idx_reproc = get_idx(["reprocessar"])

            if idx_reproc is None:
                return []

            items_to_reprocess = []
            for row_num, r in enumerate(rows[1:], start=2):
                if idx_reproc < len(r):
                    val_reproc = str(r[idx_reproc]).strip().lower()
                    if val_reproc in ["sim", "s", "yes", "y", "true", "1", "x", "reprocessar"]:
                        def val_at(idx):
                            return r[idx].strip() if idx is not None and idx < len(r) else ""

                        items_to_reprocess.append({
                            "row_index": row_num,
                            "numero_documento": val_at(idx_doc),
                            "tipo_documento": val_at(idx_tipo),
                            "fornecedor": val_at(idx_forn),
                            "farmacia": val_at(idx_farm),
                            "data_documento": val_at(idx_data),
                            "data_vencimento": val_at(idx_venc),
                            "valor_total": val_at(idx_val),
                            "numero_lote_associado": val_at(idx_lote),
                            "file_url": val_at(idx_file),
                            "nota": val_at(idx_nota),
                            "nif_fornecedor": val_at(idx_nif),
                        })
            return items_to_reprocess
        except Exception as e:
            print(f"Aviso ao verificar linhas para reprocessar: {e}")
            return []

    def update_reprocessed_row(self, row_index: int, new_filename: str = "", new_drive_url: str = None, new_confianca: str = "Validado (Manual)", new_nota: str = ""):
        """
        Atualiza o estado de uma linha reprocessada na aba 'Registo':
        - Atualiza Ficheiro com HYPERLINK(url, nome_ficheiro)
        - Confiança = 'Validado (Manual)'
        - Nota = limpa ou atualizada
        - Reprocessar = 'Concluído'
        """
        if self.is_offline or not self.service:
            return
        try:
            # Ler cabeçalhos para saber as colunas certas
            res = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'Registo'!A{row_index}:O{row_index}"
            ).execute()
            row_vals = res.get('values', [[]])[0]
            while len(row_vals) < 15:
                row_vals.append("")

            if new_drive_url and str(new_drive_url).startswith("http"):
                display_name = new_filename or "Ver Ficheiro"
                file_cell = f'=HYPERLINK("{new_drive_url}"; "{display_name}")'
            else:
                file_cell = str(new_drive_url or new_filename or "")

            headers = self.get_sheet_headers("Registo")
            for i, h in enumerate(headers):
                hl = h.lower()
                if ("ficheiro" in hl or "link" in hl) and new_drive_url:
                    row_vals[i] = file_cell
                elif "confian" in hl:
                    row_vals[i] = new_confianca
                elif "nota" in hl:
                    row_vals[i] = new_nota
                elif "reprocessar" in hl:
                    row_vals[i] = "Concluído"

            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'Registo'!A{row_index}:O{row_index}",
                valueInputOption="USER_ENTERED",
                body={'values': [row_vals]}
            ).execute()
        except Exception as e:
            print(f"Erro ao atualizar linha {row_index} reprocessada: {e}")

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
        Mostra o nome do ficheiro formatado como link clicável via HYPERLINK.
        """
        self.ensure_registo_sheet_exists()
        self.ensure_resumo_sheet_exists()

        existing_headers = self.get_sheet_headers("Registo")

        data_venc = str(doc_data.get("data_vencimento") or doc_data.get("data_documento") or "")
        nif_fornecedor = str(doc_data.get("nif_fornecedor") or "")
        filename_display = str(doc_data.get("nome_ficheiro_novo") or doc_data.get("ficheiro_original") or "Ver Ficheiro")

        if drive_url and str(drive_url).startswith("http"):
            ficheiro_cell = f'=HYPERLINK("{drive_url}"; "{filename_display}")'
        else:
            ficheiro_cell = str(drive_url or filename_display)

        mapping = {
            "Nº Documento": str(doc_data.get("numero_documento") or doc_data.get("numero_lote") or ""),
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
            "Ficheiro": ficheiro_cell,
            "Ficheiro (link Drive)": ficheiro_cell,
            "Nota": str(doc_data.get("nota") or ""),
            "NIF Fornecedor": nif_fornecedor,
            "Reprocessar": ""
        }

        if existing_headers:
            row_values = []
            for col in existing_headers:
                col_clean = col.strip()
                if "fatura" in col_clean.lower() or "ficheiro" in col_clean.lower() or "link" in col_clean.lower():
                    row_values.append(ficheiro_cell)
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
                elif "reprocessar" in col_clean.lower():
                    row_values.append("")
                else:
                    row_values.append(mapping.get(col_clean, ""))
        else:
            row_values = [
                str(doc_data.get("numero_documento") or doc_data.get("numero_lote") or ""),
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
                ficheiro_cell,
                str(doc_data.get("nota") or ""),
                nif_fornecedor,
                ""
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
