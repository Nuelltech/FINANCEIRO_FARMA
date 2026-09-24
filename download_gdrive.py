import os
import sys
import glob

FOLDER_URL = "https://drive.google.com/drive/folders/13B0ztENtz3PaEUpi4a2c1WY1L6VCSFkq"
INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")

def download_folder():
    os.makedirs(INPUT_DIR, exist_ok=True)
    existing = glob.glob(os.path.join(INPUT_DIR, "*.pdf"))
    if len(existing) >= 20:
        print(f"Pasta local 'input/' já contém {len(existing)} ficheiros PDF. Ignorando download repetido.")
        return
        
    print(f"Descarregando ficheiros da pasta do Google Drive para: {INPUT_DIR}...")
    try:
        import gdown
        gdown.download_folder(url=FOLDER_URL, output=INPUT_DIR, quiet=True, use_cookies=False)
        print("Download concluído com sucesso!")
    except Exception as e:
        print(f"Aviso ao descarregar via gdown: {e}")

if __name__ == "__main__":
    download_folder()
