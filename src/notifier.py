import os
import datetime

class ExecutionLogger:
    """
    Gerencia o registo auditável de execução na aba 'Log de Execuções' do Google Sheets
    (Requisito 3.9 do PRD - Sem Slack por agora).
    """
    def __init__(self, sheets_service):
        self.sheets_service = sheets_service

    def log_execution(self, total_docs: int, qtd_alta: int, qtd_media: int, qtd_baixa: int, total_pending: float, origem_instrucoes: str, notas_adicionais: str = ""):
        timestamp_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        summary_note = f"{total_docs} doc(s) analisado(s). {qtd_baixa} enviado(s) para A Rever."
        if notas_adicionais:
            summary_note += f" | {notas_adicionais}"

        log_data = {
            "timestamp_utc": timestamp_now,
            "total_processados": total_docs,
            "qtd_alta": qtd_alta,
            "qtd_media": qtd_media,
            "qtd_baixa": qtd_baixa,
            "total_pendente": total_pending,
            "origem_instrucoes": origem_instrucoes,
            "resumo_notas": summary_note
        }

        print("\n" + "=" * 80)
        print("   RESUMO DE REGISTO DE EXECUÇÃO (LOG DE EXECUÇÕES)   ")
        print("=" * 80)
        print(f"  Data/Hora UTC: {timestamp_now}")
        print(f"  Total Processados: {total_docs}")
        print(f"  Confiança -> Alta: {qtd_alta} | Média: {qtd_media} | Baixa (A Rever): {qtd_baixa}")
        print(f"  Total Pendente (€): {total_pending:,.2f} €")
        print(f"  Origem Instruções: {origem_instrucoes}")
        print(f"  Notas: {summary_note}")
        print("=" * 80 + "\n")

        if self.sheets_service:
            self.sheets_service.append_execution_log(log_data)
