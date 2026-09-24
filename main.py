import os
import sys
import json
import tempfile

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.gdrive_service import GDriveService
from src.vision_extractor import VisionExtractor
from src.validation_rules import ValidationRules
from src.sheets_service import SheetsService
from src.supabase_service import SupabaseService
from src.notifier import SlackNotifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "gdrive_folder_id": "13B0ztENtz3PaEUpi4a2c1WY1L6VCSFkq",
        "gsheet_id": "1vTgzYj7Bund21oW2EJtBRXo4otXGgvEynzwmfgCXYIY",
        "input_dir": "input",
        "output_dir": "output",
        "data_dir": "data",
        "llm_provider": "anthropic"
    }

def run_pipeline():
    print("=" * 80)
    print("   PIPELINE DIÁRIO DE PROCESSAMENTO DE FATURAS - FARMÁCIA PILOTO (FASE 1)   ")
    print("=" * 80)

    config = load_config()
    input_dir = os.path.join(BASE_DIR, config.get("input_dir", "input"))
    output_dir = os.path.join(BASE_DIR, config.get("output_dir", "output"))
    data_dir = os.path.join(BASE_DIR, config.get("data_dir", "data"))

    # 1. Inicialização dos Serviços
    gdrive_service = GDriveService(
        folder_id=config["gdrive_folder_id"],
        local_input_dir=input_dir,
        local_output_dir=output_dir
    )
    sheets_service = SheetsService(
        spreadsheet_id=config["gsheet_id"],
        local_excel_path=os.path.join(output_dir, "relatorio_faturas.xlsx"),
        local_json_path=os.path.join(data_dir, "documentos.json")
    )
    supabase_service = SupabaseService(
        local_state_path=os.path.join(data_dir, "processed_state.json")
    )
    extractor = VisionExtractor(provider=config.get("llm_provider", "anthropic"))
    notifier = SlackNotifier()

    # 2. Deteção de ficheiros novos no Google Drive
    print("\n[1/4] A consultar ficheiros novos no Google Drive...")
    new_files = gdrive_service.list_new_files()
    if not new_files:
        print("Nenhum ficheiro novo encontrado para processar.")
        notifier.send_daily_summary(0, 0, 0.0, 0)
        return

    print(f"Encontrados {len(new_files)} ficheiro(s) novo(s) para analisar.\n")

    # 3. Processamento de cada documento
    processed_count = 0
    review_count = 0
    total_pending_amount = 0.0

    with tempfile.TemporaryDirectory() as temp_dir:
        for i, file_info in enumerate(new_files, 1):
            filename = file_info["name"]
            file_id = file_info["id"]
            print(f"--- [{i}/{len(new_files)}] A analisar: {filename} (ID: {file_id}) ---")

            # Transferir ficheiro para pasta temporária de análise
            local_pdf = os.path.join(temp_dir, f"temp_{i}.pdf")
            gdrive_service.download_file(file_id, local_pdf)

            # Extração Multimodal por Visão LLM
            raw_data = extractor.extract_from_pdf(local_pdf)
            raw_data["ficheiro_original"] = filename

            # Validação Cruzada & Duplo Filtro de Confiança
            doc_data = ValidationRules.validate_extraction(raw_data, filename)

            # Verificar Deduplicação no Supabase
            if supabase_service.is_file_processed(file_id, doc_data.get("numero_documento"), doc_data.get("fornecedor")):
                print(f"  [Dedupe] Documento {filename} já processado anteriormente. A ignorar reprocessamento.")
                doc_data["confianca"] = "Baixa"
                doc_data["nota"] = "Documento em duplicado"

            # Tratar Resumos de Lote (Opção B PRD)
            if doc_data.get("tipo_documento") == "Resumo de Lote" and doc_data.get("confianca") != "Baixa":
                supabase_service.record_batch_summary(doc_data, file_id)

            # Organizar (renomear e mover) no Google Drive
            org_info = gdrive_service.organize_file(file_info, doc_data)
            drive_url = org_info.get("drive_url", "")
            new_name = org_info.get("new_filename", filename)

            # Registar no Supabase (Base de dados de controlo)
            supabase_service.record_processed_file(doc_data, file_id, drive_url, new_name)

            # Anexar linha no Google Sheets nativo (spreadsheets.values.append)
            sheets_service.append_document_row(doc_data, drive_url)

            # Atualizar Métricas do Alerta
            if doc_data.get("confianca") == "Baixa" or doc_data.get("categoria_pasta") == "A Rever":
                review_count += 1
            else:
                processed_count += 1
                if doc_data.get("tipo_documento") in ["Fatura", "Nota de Crédito"]:
                    val = float(doc_data.get("valor_total") or 0.0)
                    total_pending_amount += val

            print(f"  Tipo: {doc_data['tipo_documento']} | Farmácia: {doc_data['farmacia']}")
            print(f"  Fornecedor: {doc_data['fornecedor']} | N.º Doc: {doc_data['numero_documento']}")
            print(f"  Valor: {doc_data['valor_total']} € | Confiança: {doc_data['confianca']}")
            print(f"  Novo Nome: {new_name}")
            print(f"  Destino: {org_info.get('subpath')}\n")

    # 4. Envio de Alerta Diário para o Slack
    notifier.send_daily_summary(processed_count, review_count, total_pending_amount, len(new_files))

    print("=" * 80)
    print("PIPELINE CONCLUÍDO COM SUCESSO!")
    print("=" * 80)

if __name__ == "__main__":
    run_pipeline()
