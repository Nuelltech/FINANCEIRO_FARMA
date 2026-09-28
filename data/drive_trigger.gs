/**
 * Google Apps Script para disparo automático do pipeline no GitHub Actions ao detetar novas faturas.
 * Pasta Root: 13B0ztENtz3PaEUpi4a2c1WY1L6VCSFkq
 */

const GITHUB_TOKEN = "O_SEU_GITHUB_PAT_AQUI"; // Cole aqui o seu Personal Access Token do GitHub (ghp_...)
const REPO_OWNER = "Nuelltech";
const REPO_NAME = "FINANCEIRO_FARMA";
const DRIVE_FOLDER_ID = "13B0ztENtz3PaEUpi4a2c1WY1L6VCSFkq";
const NOTIFICATION_EMAIL = ""; // Opcional: coloque o email do gestor para receber alertas (ex: gestao@farmacia.pt)

function checkAndTriggerPipeline() {
  const folder = DriveApp.getFolderById(DRIVE_FOLDER_ID);
  const files = folder.getFiles();
  let pdfCount = 0;

  while (files.hasNext()) {
    const file = files.next();
    const name = file.getName().toLowerCase();
    
    // Contar apenas PDFs que não sejam pastas de configuração ou ficheiros temporários
    if (name.endsWith(".pdf") && !name.startsWith("_config")) {
      pdfCount++;
    }
  }

  if (pdfCount > 0) {
    Logger.log(`Encontrados ${pdfCount} novos ficheiros PDF na pasta root. A disparar o pipeline no GitHub Actions...`);
    
    const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/daily_pipeline.yml/dispatches`;
    const payload = JSON.stringify({ ref: "main" });
    
    const options = {
      method: "post",
      headers: {
        "Authorization": `Bearer ${GITHUB_TOKEN}`,
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
      },
      payload: payload,
      muteHttpExceptions: true
    };

    try {
      const response = UrlFetchApp.fetch(url, options);
      const code = response.getResponseCode();
      
      if (code === 204) {
        Logger.log("Pipeline disparado com SUCESSO no GitHub Actions!");
        
        // Enviar email opcional de confirmação ao gestor
        if (NOTIFICATION_EMAIL) {
          MailApp.sendEmail({
            to: NOTIFICATION_EMAIL,
            subject: `🚀 [FINANCEIRO FARMA] Processamento de ${pdfCount} fatura(s) iniciado!`,
            body: `Foram detetados ${pdfCount} novos documentos PDF na pasta do Google Drive. O processamento automático foi iniciado com sucesso.`
          });
        }
      } else {
        Logger.log(`Erro ao disparar pipeline. Código HTTP: ${code} - Resposta: ${response.getContentText()}`);
      }
    } catch (e) {
      Logger.log(`Exceção ao ligar ao GitHub API: ${e.message}`);
    }
  } else {
    Logger.log("Nenhum ficheiro novo PDF encontrado na pasta root.");
  }
}
