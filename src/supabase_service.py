import os
import json
from supabase import create_client, Client

class SupabaseService:
    """
    Serviço de controlo de estado, auditoria e deduplicação no Supabase.
    Previne reprocessamento e suporta a regra Opção B do PRD para Resumos de Lote.
    Possui fallback gracioso em ficheiro JSON local quando executado sem credenciais.
    """
    def __init__(self, local_state_path: str = "data/processed_state.json"):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
        self.local_state_path = local_state_path
        self.client: Client = None
        self.is_offline = True

        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
                self.is_offline = False
                print("Supabase Client autenticado com sucesso.")
            except Exception as e:
                print(f"Erro ao inicializar Supabase: {e}")

        if self.is_offline:
            print("Supabase a funcionar em modo offline (base de dados JSON local).")

    def is_file_processed(self, drive_file_id: str, num_doc: str = None, fornecedor: str = None) -> bool:
        """Verifica se um ficheiro ou combinação (num_doc + fornecedor) já foi processado."""
        if not self.is_offline:
            try:
                res = self.client.table("faturas_processadas").select("id").eq("drive_file_id", drive_file_id).execute()
                if res.data and len(res.data) > 0:
                    return True
                
                if num_doc and fornecedor and num_doc != "SEM_NUM":
                    res_doc = self.client.table("faturas_processadas").select("id").eq("numero_documento", num_doc).eq("fornecedor", fornecedor).execute()
                    if res_doc.data and len(res_doc.data) > 0:
                        return True
                return False
            except Exception as e:
                print(f"Aviso ao consultar Supabase: {e}")

        # Fallback local
        state = self._load_local_state()
        if drive_file_id in state.get("file_ids", []):
            return True
        if num_doc and fornecedor and num_doc != "SEM_NUM":
            key = f"{fornecedor}_{num_doc}"
            if key in state.get("doc_keys", []):
                return True
        return False

    def record_processed_file(self, doc_data: dict, drive_file_id: str, drive_url: str, new_filename: str) -> bool:
        """Regista um documento (fatura, nota de crédito ou A Rever) no Supabase."""
        status = "A_REVER" if doc_data.get("confianca") == "Baixa" else "PROCESSADO"
        
        record = {
            "drive_file_id": drive_file_id,
            "nome_ficheiro_original": doc_data.get("ficheiro_original", ""),
            "nome_ficheiro_novo": new_filename,
            "fornecedor": doc_data.get("fornecedor"),
            "nif_fornecedor": doc_data.get("nif_fornecedor"),
            "farmacia": doc_data.get("farmacia"),
            "tipo_documento": doc_data.get("tipo_documento"),
            "numero_documento": doc_data.get("numero_documento"),
            "data_documento": doc_data.get("data_documento"),
            "data_vencimento": doc_data.get("data_vencimento"),
            "valor_total": doc_data.get("valor_total"),
            "confianca": doc_data.get("confianca"),
            "motivo_baixa_confianca": doc_data.get("motivo_baixa_confianca"),
            "status_processamento": status,
            "numero_lote_associado": doc_data.get("numero_lote_associado"),
            "drive_file_url": drive_url
        }

        if not self.is_offline:
            try:
                self.client.table("faturas_processadas").upsert(record, on_conflict="drive_file_id").execute()
                return True
            except Exception as e:
                print(f"Erro ao registar fatura no Supabase: {e}")

        # Fallback local
        state = self._load_local_state()
        if drive_file_id not in state["file_ids"]:
            state["file_ids"].append(drive_file_id)
        
        forn = doc_data.get("fornecedor")
        num = doc_data.get("numero_documento")
        if forn and num:
            doc_key = f"{forn}_{num}"
            if doc_key not in state["doc_keys"]:
                state["doc_keys"].append(doc_key)
        
        state["records"].append(record)
        self._save_local_state(state)
        return True

    def record_batch_summary(self, doc_data: dict, drive_file_id: str) -> bool:
        """Regista um Resumo de Lote no Supabase (Opção B do PRD)."""
        faturas_agregadas = doc_data.get("faturas_agregadas", [])
        record = {
            "drive_file_id": drive_file_id,
            "numero_lote": doc_data.get("numero_documento") or "LOTE_SEM_NUM",
            "fornecedor": doc_data.get("fornecedor", ""),
            "farmacia": doc_data.get("farmacia", ""),
            "data_lote": doc_data.get("data_documento"),
            "valor_total_lote": doc_data.get("valor_total", 0.0),
            "lista_faturas_agregadas": faturas_agregadas,
            "lote_conciliado": False
        }

        if not self.is_offline:
            try:
                self.client.table("resumos_lote").insert(record).execute()
                print(f"  [Supabase] Resumo de Lote {record['numero_lote']} registado com sucesso.")
                return True
            except Exception as e:
                print(f"Erro ao registar Resumo de Lote no Supabase: {e}")

        # Fallback local
        state = self._load_local_state()
        state.setdefault("resumos_lote", []).append(record)
        self._save_local_state(state)
        return True

    def get_all_batch_summaries(self) -> list:
        """Obtém todos os resumos de lote registados (para conciliação com faturas)."""
        if not self.is_offline and self.client:
            try:
                res = self.client.table("resumos_lote").select("*").execute()
                return res.data or []
            except Exception as e:
                print(f"Aviso ao consultar resumos_lote do Supabase: {e}")

        state = self._load_local_state()
        return state.get("resumos_lote", [])

    def update_batch_reconciliation(self, numero_lote: str, lote_conciliado: bool, valor_apurado: float = 0.0) -> bool:
        """Atualiza o estado de conciliação matemática de um resumo de lote."""
        if not self.is_offline and self.client:
            try:
                self.client.table("resumos_lote").update({
                    "lote_conciliado": lote_conciliado,
                    "valor_apurado": valor_apurado
                }).eq("numero_lote", str(numero_lote)).execute()
                return True
            except Exception as e:
                print(f"Aviso ao atualizar estado de conciliação no Supabase: {e}")

        state = self._load_local_state()
        for batch in state.get("resumos_lote", []):
            if str(batch.get("numero_lote")) == str(numero_lote):
                batch["lote_conciliado"] = lote_conciliado
                batch["valor_apurado"] = valor_apurado
        self._save_local_state(state)
        return True

    def _load_local_state(self) -> dict:
        os.makedirs(os.path.dirname(self.local_state_path), exist_ok=True)
        if os.path.exists(self.local_state_path):
            try:
                with open(self.local_state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"file_ids": [], "doc_keys": [], "records": [], "resumos_lote": []}

    def _save_local_state(self, state: dict):
        os.makedirs(os.path.dirname(self.local_state_path), exist_ok=True)
        with open(self.local_state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
