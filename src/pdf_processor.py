import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import pymupdf
from PIL import Image
import easyocr
import numpy as np

class PDFProcessor:
    def __init__(self, languages=['pt', 'en']):
        print("Inicializando leitor OCR EasyOCR (com fundo branco na rotação)...")
        self.reader = easyocr.Reader(languages, gpu=False, verbose=False)

    def pdf_to_image(self, pdf_path: str, page_num: int = 0, dpi: int = 150) -> Image.Image:
        doc = pymupdf.open(pdf_path)
        page = doc[page_num]
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return img

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Converte a 1ª página do PDF para imagem a 150 DPI e executa OCR.
        Testa rotações (0°, 180°, 90°, 270°) com fundo branco preenchido.
        """
        img = self.pdf_to_image(pdf_path, dpi=150)
        
        best_text = ""
        best_score = -1.0

        for angle in [0, 180, 90, 270]:
            if angle == 0:
                rotated_img = img
            else:
                rotated_img = img.rotate(angle, expand=True, fillcolor=(255, 255, 255))

            img_np = np.array(rotated_img)
            
            try:
                results = self.reader.readtext(img_np, detail=0)
                text = " ".join(results)
            except Exception:
                text = ""

            score = self._evaluate_text(text)
            
            if score > best_score:
                best_score = score
                best_text = text
                
            # Se encontrou pontuação excelente (palavras-chave chave), aceita e sai do loop
            if score >= 25:
                break

        return best_text

    def _evaluate_text(self, text: str) -> float:
        text_upper = text.upper()
        score = 0.0
        keywords = ["FACTURA", "FATURA", "COOPROFAR", "RESUMO", "NIF", "VALOR", "DATA", "BAPTISTA", "EXTRACTO", "GUIA", "TOTAL", "CONTRIB"]
        for kw in keywords:
            if kw in text_upper:
                score += 15.0
        return score
