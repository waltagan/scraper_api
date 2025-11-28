import fitz  # PyMuPDF
import httpx
import logging
from app.core.proxy import proxy_manager

logger = logging.getLogger(__name__)

async def download_and_extract(pdf_url: str) -> str:
    """
    Downloads a PDF from the given URL and extracts text from the first 3 and last 2 pages.
    """
    try:
        # Get a proxy to avoid blocking
        proxy = await proxy_manager.get_next_proxy()
        
        async with httpx.AsyncClient(proxies=proxy, verify=False) as client:
            # Add headers to mimic a browser, often needed for PDF downloads
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = await client.get(pdf_url, timeout=10.0, follow_redirects=True, headers=headers)
            response.raise_for_status()
            pdf_bytes = response.content

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        total_pages = doc.page_count

        # Determine pages to extract: Only First 2 pages (0, 1) to save time and tokens
        indices = set()
        for i in range(min(2, total_pages)):
            indices.add(i)
        
        sorted_indices = sorted(list(indices))
        
        text_parts.append(f"--- PDF START: {pdf_url} ---")
        for i in sorted_indices:
            page = doc.load_page(i)
            # clean=True helps with some layout issues, but default is usually fine for raw text
            text_parts.append(f"[Page {i+1}]\n{page.get_text()}")
        text_parts.append(f"--- PDF END: {pdf_url} ---")
            
        return "\n\n".join(text_parts)

    except Exception as e:
        logger.warning(f"Error processing PDF {pdf_url}: {e}")
        return ""

