import os
import sys
import json
import tempfile
import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.gdrive_service import GDriveService
from src.vision_extractor import VisionExtractor
from src.validation_rules import ValidationRules
from src.sheets_service import SheetsService
from src.supabase_service import SupabaseService
from src.notifier import ExecutionLogger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# IDs dos Google Docs de Configuração do Agente na pasta _Config Agente
PROMPT_EXTRACAO_DOC_ID = "19xU7aksSo0RV45BoxwKSNov3Ast8qsYlW2ewrPNDYG4"
CONTEXTO_INSTRUCION_DOC_ID = "1_zbYX09PCqsJ6uJddo4fC3yc6BG5dXkXhw4ysYC32t4"

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

def load_instructions(gdrive_service: GDriveService) -> tuple:
    """
    Carrega os prompts e instruções de negócio.
    Sincroniza automaticamente as novas regras no Google Doc em _Config Agente.
    """
    print("\n[0/4] A carregar e sincronizar instruções do Agente...")
    
    from src.vision_extractor import DEFAULT_SYSTEM_PROMPT
    
    # Sincronizar automaticamente o Google Doc em _Config Agente com o prompt mais recente
    if not gdrive_service.is_offline and gdrive_service.service:
        gdrive_service.update_google_doc_text(PROMPT_EXTRACAO_DOC_ID, DEFAULT_SYSTEM_PROMPT)

    try:
        prompt_text = gdrive_service.export_google_doc_text(PROMPT_EXTRACAO_DOC_ID)
        context_text = gdrive_service.export_google_doc_text(CONTEXTO_INSTRUCION_DOC_ID)
        origem = "Google Docs (_Config Agente)"
        print("  [Sucesso] Instruções sincronizadas e carregadas a partir do Google Docs.")
        return prompt_text, context_text, origem
    except Exception as e:
        print(f"  [Aviso] Falha ao ler Google Docs ({e}). A recorrer às instruções nativas do sistema...")
        return DEFAULT_SYSTEM_PROMPT, "", "Instruções Nativas do Agente"

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
    logger = ExecutionLogger(sheets_service=sheets_service)

    # 2. Carregamento Dinâmico de Instruções (Google Docs vs TXT Fallback)
    system_prompt, context_instructions, origem_instrucoes = load_instructions(gdrive_service)

    # 3. Deteção de ficheiros novos no Google Drive (ignorando _Config Agente)
    print("\n[1/4] A consultar ficheiros novos no Google Drive...")
    new_files = gdrive_service.list_new_files()
    if not new_files:
        print("Nenhum ficheiro novo encontrado para processar.")
        logger.log_execution(0, 0, 0, 0, 0.0, origem_instrucoes, "Sem ficheiros novos.")
        return

    print(f"Encontrados {len(new_files)} ficheiro(s) novo(s) para analisar.\n")

    # 4. Processamento de cada documento
    qtd_alta = 0
    qtd_media = 0
    qtd_baixa = 0
    total_pending_amount = 0.0

    with tempfile.TemporaryDirectory() as temp_dir:
        for i, file_info in enumerate(new_files, 1):
            filename = file_info["name"]
            file_id = file_info["id"]
            print(f"--- [{i}/{len(new_files)}] A analisar: {filename} (ID: {file_id}) ---")

            # Transferir ficheiro para pasta temporária de análise
            local_pdf = os.path.join(temp_dir, f"temp_{i}.pdf")
            gdrive_service.download_file(file_id, local_pdf)

            # Extração Multimodal por Visão LLM (com prompt dinâmico)
            raw_data = extractor.extract_from_pdf(local_pdf, system_prompt=system_prompt)
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

            # Contabilidade de Métricas
            conf = doc_data.get("confianca", "Baixa")
            if conf == "Alta":
                qtd_alta += 1
            elif conf == "Media" or conf == "Média":
                qtd_media += 1
            else:
                qtd_baixa += 1

            if doc_data.get("confianca") != "Baixa" and doc_data.get("tipo_documento") in ["Fatura", "Nota de Crédito"]:
                val = float(doc_data.get("valor_total") or 0.0)
                total_pending_amount += val

            print(f"  Tipo: {doc_data['tipo_documento']} | Farmácia: {doc_data['farmacia']}")
            print(f"  Fornecedor: {doc_data['fornecedor']} | N.º Doc: {doc_data['numero_documento']}")
            print(f"  Valor: {doc_data['valor_total']} € | Confiança: {doc_data['confianca']}")
            print(f"  Novo Nome: {new_name}")
            print(f"  Destino: {org_info.get('subpath')}\n")

    # 5. Registo Auditável de Execução na Aba 'Log de Execuções' do Google Sheets
    logger.log_execution(
        total_docs=len(new_files),
        qtd_alta=qtd_alta,
        qtd_media=qtd_media,
        qtd_baixa=qtd_baixa,
        total_pending=total_pending_amount,
        origem_instrucoes=origem_instrucoes
    )

    print("=" * 80)
    print("PIPELINE CONCLUÍDO COM SUCESSO!")
    print("=" * 80)

if __name__ == "__main__":
    run_pipeline()
