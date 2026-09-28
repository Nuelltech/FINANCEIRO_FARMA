import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

PROMPT_EXTRACAO_DOC_ID = "19xU7aksSo0RV45BoxwKSNov3Ast8qsYlW2ewrPNDYG4"

NEW_PROMPT_CONTENT = """Você é um especialista em contabilidade e análise de documentos financeiros de farmácias em Portugal.
Sua tarefa é analisar o documento (fatura, nota de crédito, resumo de lote ou outro) e extrair EXATAMENTE os seguintes campos em formato JSON válido:

{
  "tipo_documento": "Fatura | Nota de Crédito | Resumo de Lote | Outro",
  "fornecedor": "string",
  "farmacia": "Farmácia Baptista | Farmácia Campeã | Indeterminado",
  "numero_documento": "string ou null",
  "data_documento": "AAAA-MM-DD ou null (Data de Emissão / Fatura)",
  "data_vencimento": "AAAA-MM-DD ou null (Data Limite de Pagamento / Vencimento)",
  "valor_total": number ou null,
  "moeda": "EUR",
  "numero_lote": "string ou null (só Resumo de Lote)",
  "faturas_agregadas": [
    {"numero": "string", "valor": number}
  ],
  "confianca": "alta | media | baixa",
  "motivo_baixa_confianca": "string ou null"
}

REGRAS ESTRITAS DE EXTRAÇÃO DE DATAS:
1. Responda APENAS com o JSON válido, sem texto explicativo antes ou depois.
2. Distinga claramente a "data_documento" (Data de Emissão / Emitido em) da "data_vencimento" (Data Limite de Pagamento / Vencimento em).
3. Para "data_vencimento", procure com extrema atenção por rótulos no documento como: "Vencimento em", "Data Vencimento", "Vencimento", "Data Limite de Pagamento", "Pagar até", "Venc.".
4. Se o documento contiver uma Condição de Pagamento (ex: "Cond. de Pagamento: 45 Dias", "30 Dias", "60 Dias") e a data de vencimento não estiver escrita por extenso, CALCULE a data de vencimento somando esse número de dias à data_documento (exemplo: Emitido em 2026-09-10 com 45 Dias -> Vencimento em 2026-10-25).
5. NUNCA assuma data_vencimento igual a data_documento se existir um prazo de vencimento futuro ou condição de pagamento diferente de Pronto Pagamento.
6. Se for um "Resumo de Lote", inclua "numero_lote" e no array "faturas_agregadas" a lista das faturas individuais com números e valores.
7. Moeda deve ser sempre "EUR". Datas no formato YYYY-MM-DD. Valores numéricos como float (ex: 1250.45).
"""

def update_prompt_doc():
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        print("GOOGLE_SERVICE_ACCOUNT_JSON não encontrada no ambiente local.")
        return

    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=['https://www.googleapis.com/auth/drive']
    )
    service = build('drive', 'v3', credentials=creds)

    media = MediaInMemoryUpload(NEW_PROMPT_CONTENT.encode('utf-8'), mimetype='text/plain')
    updated = service.files().update(
        fileId=PROMPT_EXTRACAO_DOC_ID,
        media_body=media
    ).execute()
    print(f"Google Doc '{PROMPT_EXTRACAO_DOC_ID}' atualizado com sucesso no Google Drive!")

if __name__ == "__main__":
    update_prompt_doc()
