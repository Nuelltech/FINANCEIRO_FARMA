import os
import json
import shutil
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

CONFIG_FOLDER_ID = "1hKHfqTrUZ39ydf9GSKMHOs2ubPSeSyXA" # Pasta _Config Agente

class GDriveService:
    """
    Serviço de integração nativa com a Google Drive API v3.
    Gerencia listagem, leitura de Google Docs, renomeação e movimentação de ficheiros.
    """
    def __init__(self, folder_id: str, credentials_json_path: str = None, local_input_dir: str = "input", local_output_dir: str = "output"):
        self.folder_id = folder_id
        self.local_input_dir = local_input_dir
        self.local_output_dir = local_output_dir
        self.service = None
        self.is_offline = True

        creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if creds_json:
            try:
                info = json.loads(creds_json)
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=['https://www.googleapis.com/auth/drive']
                )
                self.service = build('drive', 'v3', credentials=creds)
                self.is_offline = False
                print("Google Drive API v3 autenticada com sucesso (via ENV JSON).")
            except Exception as e:
                print(f"Erro ao autenticar GDrive com ENV JSON: {e}")

        elif credentials_json_path and os.path.exists(credentials_json_path):
            try:
                creds = service_account.Credentials.from_service_account_file(
                    credentials_json_path, scopes=['https://www.googleapis.com/auth/drive']
                )
                self.service = build('drive', 'v3', credentials=creds)
                self.is_offline = False
                print(f"Google Drive API v3 autenticada com sucesso (via {credentials_json_path}).")
            except Exception as e:
                print(f"Erro ao autenticar GDrive com ficheiro {credentials_json_path}: {e}")

        if self.is_offline:
            print("Google Drive API a funcionar em modo offline (ficheiros locais).")

    def export_google_doc_text(self, doc_id: str) -> str:
        """
        Exporta o conteúdo de um Google Doc como texto simples via Drive API.
        Devolve o conteúdo em texto ou lança exceção em caso de erro.
        """
        if self.is_offline or not self.service:
            raise RuntimeError("Drive API offline ou sem autenticação.")
        try:
            content_bytes = self.service.files().export(fileId=doc_id, mimeType='text/plain').execute()
            return content_bytes.decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"Falha ao exportar Google Doc {doc_id}: {e}")

    def list_new_files(self) -> list:
        """
        Lista os ficheiros PDF novos na pasta raiz do Drive.
        Exclui ficheiros contidos na pasta de configuração (_Config Agente).
        """
        if self.is_offline:
            os.makedirs(self.local_input_dir, exist_ok=True)
            files = []
            for fname in os.listdir(self.local_input_dir):
                if fname.lower().endswith(".pdf") and not fname.startswith("[PROCESSADO]"):
                    files.append({
                        "id": fname,
                        "name": fname,
                        "local_path": os.path.join(self.local_input_dir, fname),
                        "web_view_link": f"file:///{os.path.abspath(os.path.join(self.local_input_dir, fname))}"
                    })
            return files

        try:
            query = f"'{self.folder_id}' in parents and mimeType='application/pdf' and trashed=false"
            results = self.service.files().list(
                q=query,
                fields="files(id, name, webViewLink, parents)"
            ).execute()
            files = results.get('files', [])
            
            new_files = []
            for f in files:
                parents = f.get('parents', [])
                # Ignorar ficheiros na pasta _Config Agente
                if CONFIG_FOLDER_ID in parents:
                    continue
                # Ignorar ficheiros já processados ou marcados com _AREVER
                if not f['name'].startswith("[PROCESSADO]") and "_AREVER" not in f['name']:
                    new_files.append({
                        "id": f['id'],
                        "name": f['name'],
                        "web_view_link": f.get('webViewLink', f"https://drive.google.com/file/d/{f['id']}/view"),
                        "parents": parents
                    })
            return new_files
        except Exception as e:
            print(f"Erro ao listar ficheiros no Google Drive: {e}")
            return []

    def download_file(self, file_id: str, dest_path: str) -> str:
        """Transfere um ficheiro do Drive para um caminho local temporário."""
        if self.is_offline:
            src_path = os.path.join(self.local_input_dir, file_id)
            if os.path.exists(src_path) and src_path != dest_path:
                shutil.copy2(src_path, dest_path)
            return dest_path

        request = self.service.files().get_media(fileId=file_id)
        with open(dest_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        return dest_path

    def organize_file(self, file_info: dict, metadata: dict) -> dict:
        """Renomeia e move o ficheiro no Google Drive."""
        farmacia = metadata.get("farmacia", "Indeterminado")
        categoria = metadata.get("categoria_pasta", "A Rever")
        confianca = metadata.get("confianca", "Baixa")
        
        fornecedor = str(metadata.get("fornecedor", "DESCONHECIDO")).replace(" ", "_")
        farmacia_clean = str(farmacia).replace(" ", "_")
        data_str = str(metadata.get("data_documento") or "2026-01-01")
        num_doc = str(metadata.get("numero_documento") or "SEM_NUM").replace("/", "_").replace("\\", "_")

        if confianca == "Baixa" or categoria == "A Rever":
            orig_name_no_ext = os.path.splitext(file_info['name'])[0]
            new_filename = f"{orig_name_no_ext}_AREVER.pdf"
            subpath = "A Rever"
        else:
            new_filename = f"{fornecedor}_{farmacia_clean}_{data_str}_{num_doc}.pdf"
            if farmacia in ["Farmácia Baptista", "Farmácia Campeã"]:
                subpath = f"{farmacia}/{categoria}"
            else:
                subpath = f"A Rever"

        if self.is_offline:
            target_dir = os.path.join(self.local_output_dir, subpath)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, new_filename)
            
            local_src = file_info.get("local_path", os.path.join(self.local_input_dir, file_info['id']))
            if os.path.exists(local_src):
                shutil.copy2(local_src, target_path)
                proc_name = f"[PROCESSADO] {new_filename}"
                proc_path = os.path.join(self.local_input_dir, proc_name)
                try:
                    os.rename(local_src, proc_path)
                except Exception:
                    pass

            return {
                "new_filename": new_filename,
                "drive_url": f"file:///{os.path.abspath(target_path)}",
                "subpath": subpath
            }

        try:
            target_folder_id = self._get_or_create_subfolder(subpath)
            file = self.service.files().get(fileId=file_info['id'], fields='parents').execute()
            previous_parents = ",".join(file.get('parents', []))
            
            updated_file = self.service.files().update(
                fileId=file_info['id'],
                body={'name': new_filename},
                addParents=target_folder_id,
                removeParents=previous_parents,
                fields='id, name, webViewLink, parents'
            ).execute()

            return {
                "new_filename": new_filename,
                "drive_url": updated_file.get('webViewLink', f"https://drive.google.com/file/d/{file_info['id']}/view"),
                "subpath": subpath
            }
        except Exception as e:
            print(f"Erro ao renomear/mover ficheiro no GDrive: {e}")
            return {
                "new_filename": file_info['name'],
                "drive_url": file_info.get('web_view_link', ''),
                "subpath": "A Rever"
            }

    def _get_or_create_subfolder(self, subpath: str) -> str:
        parts = subpath.split('/')
        current_parent_id = self.folder_id

        for part in parts:
            query = f"'{current_parent_id}' in parents and name='{part}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.service.files().list(q=query, fields="files(id, name)").execute()
            folders = results.get('files', [])

            if folders:
                current_parent_id = folders[0]['id']
            else:
                file_metadata = {
                    'name': part,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [current_parent_id]
                }
                folder = self.service.files().create(body=file_metadata, fields='id').execute()
                current_parent_id = folder.get('id')

        return current_parent_id
