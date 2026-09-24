import os
import requests
import json

class SlackNotifier:
    """
    Envia alertas e resumos diários para o Slack via Webhook (Requisito 3.9 do PRD).
    """
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")

    def send_daily_summary(self, processed_count: int, review_count: int, pending_amount: float, total_docs: int) -> bool:
        """Envia a mensagem de resumo diário formatada para o financeiro."""
        msg_parts = []
        if processed_count > 0:
            msg_parts.append(f"✅ *{processed_count}* documento(s) novos processados com sucesso.")
        if review_count > 0:
            msg_parts.append(f"⚠️ *{review_count}* documento(s) enviado(s) para revisão manual (*A Rever*).")
        
        pending_formatted = f"{pending_amount:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        msg_parts.append(f"📊 *Total pendente acumulado:* {pending_formatted}")

        full_text = f"🤖 *Pipeline Diário - Farmácia Piloto*\n" + "\n".join(msg_parts)

        print("\n--- RESUMO DE EXECUÇÃO DIÁRIA (ALERT) ---")
        print(full_text)
        print("------------------------------------------\n")

        if not self.webhook_url:
            print("  [Slack] Nenhum SLACK_WEBHOOK_URL configurado. Alerta emitido apenas na consola.")
            return False

        try:
            payload = {"text": full_text}
            res = requests.post(self.webhook_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            if res.status_code == 200:
                print("  [Slack] Notificação enviada para o Slack com sucesso!")
                return True
            else:
                print(f"  [Slack] Erro ao enviar para o Slack (Status {res.status_code}): {res.text}")
                return False
        except Exception as e:
            print(f"  [Slack] Exceção ao ligar ao webhook do Slack: {e}")
            return False
