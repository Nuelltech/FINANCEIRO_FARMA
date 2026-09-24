import os
import shutil
import json
from src.sheets_service import MasterSheetService

class DocumentOrganizer:
    def __init__(self, base_output_dir: str, data_dir: str):
        self.base_output_dir = base_output_dir
        self.data_dir = data_dir
        os.makedirs(base_output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        
        self.json_path = os.path.join(data_dir, "documentos.json")
        self.excel_path = os.path.join(base_output_dir, "relatorio_faturas.xlsx")
        self.sheet_service = MasterSheetService(self.excel_path, self.json_path)
        self.all_records = []

    def organize(self, input_pdf_path: str, metadata: dict) -> str:
        """
        Organiza o ficheiro nas categorias: Faturas, Notas_Credito, Lotes_Faturas ou Pendentes_Revisao.
        Renomeia para [PROCESSADO] FORNECEDOR_YYYY-MM-DD_TipoDoc_NumDoc.pdf
        """
        categoria_pasta = metadata.get("categoria_pasta", "Pendentes_Revisao")
        data_str = metadata.get("data_documento", "2026-01-01")
        parts = data_str.split("-")
        ano = parts[0] if len(parts) >= 1 else "2026"
        mes = parts[1] if len(parts) >= 2 else "01"

        fornecedor = metadata.get("fornecedor", "DESCONHECIDO").replace(" ", "_")
        tipo = metadata.get("tipo_documento", "OUTRO")
        num_doc = metadata.get("id_documento", "SEM_NUMERO").replace("/", "_").replace("\\", "_")

        # Criar pasta de destino
        target_dir = os.path.join(self.base_output_dir, categoria_pasta, ano, mes)
        os.makedirs(target_dir, exist_ok=True)

        # Nome normalizado do ficheiro
        new_filename = f"[PROCESSADO] {fornecedor}_{data_str}_{tipo}_{num_doc}.pdf"
        target_path = os.path.join(target_dir, new_filename)

        # Mover/Copiar o ficheiro para a pasta organizada
        shutil.copy2(input_pdf_path, target_path)
        metadata["caminho_organizado"] = target_path

        # Renomear também o ficheiro na pasta de entrada para [PROCESSADO]... para distinção visual
        input_dir = os.path.dirname(input_pdf_path)
        orig_filename = os.path.basename(input_pdf_path)
        if not orig_filename.startswith("[PROCESSADO]"):
            new_input_name = f"[PROCESSADO] {fornecedor}_{data_str}_{tipo}_{num_doc}.pdf"
            new_input_path = os.path.join(input_dir, new_input_name)
            try:
                if not os.path.exists(new_input_path):
                    os.rename(input_pdf_path, new_input_path)
            except Exception:
                pass

        self.all_records.append(metadata)
        self.sheet_service.update_master_sheet(self.all_records)

        return target_path
