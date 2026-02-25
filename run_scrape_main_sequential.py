#!/usr/bin/env python3
"""
Runner sequencial para etapas 2 e 3 do scrape_main.

Objetivo:
- Processar 1 empresa por vez.
- Buscar pendencias em paginas pequenas para evitar timeout por carga massiva.
- Gerar logs claros de progresso e erros.
"""

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import asyncpg
from dotenv import load_dotenv

from app.services.database_service import SCHEMA, get_db_service
from app.services.scraper import (
    extract_mainpage_text_from_raw,
    extract_subpage_links_from_raw,
)


def setup_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger("seq_scrape_main")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


async def fetch_pending_rows(
    conn: asyncpg.Connection,
    stage: int,
    after_id: int,
    fetch_size: int,
    statement_timeout_ms: int,
    query_timeout_s: int,
) -> List[Dict]:
    if stage == 2:
        query = f"""
            SELECT id, cnpj_basico, website_url, raw_content
            FROM "{SCHEMA}".scrape_main
            WHERE id > $1
              AND raw_content IS NOT NULL
              AND LENGTH(TRIM(raw_content)) > 0
              AND (subpage_links IS NULL OR TRIM(subpage_links) = '')
            ORDER BY id
            LIMIT $2
        """
    else:
        query = f"""
            SELECT id, cnpj_basico, website_url, raw_content
            FROM "{SCHEMA}".scrape_main
            WHERE id > $1
              AND raw_content IS NOT NULL
              AND LENGTH(TRIM(raw_content)) > 0
              AND (mainpage_processada IS NULL OR TRIM(mainpage_processada) = '')
            ORDER BY id
            LIMIT $2
        """

    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = '{statement_timeout_ms}'")
        rows = await conn.fetch(query, after_id, fetch_size, timeout=query_timeout_s)
    return [dict(r) for r in rows]


async def process_stage(
    stage: int,
    db_url: str,
    total_samples: int,
    fetch_size: int,
    progress_every: int,
    statement_timeout_ms: int,
    query_timeout_s: int,
    sleep_ms: int,
    logger: logging.Logger,
) -> Tuple[int, int, int]:
    db_service = get_db_service()
    processed = 0
    success = 0
    errors = 0
    after_id = 0
    started_at = time.time()
    retries_on_fetch = 0

    logger.info(
        "[SEQ-STEP%s] start total=%s fetch_size=%s progress_every=%s",
        stage, total_samples, fetch_size, progress_every,
    )

    conn = await asyncpg.connect(db_url)
    try:
        while processed < total_samples:
            remaining = total_samples - processed
            current_fetch = min(fetch_size, remaining)

            try:
                t_fetch0 = time.time()
                rows = await fetch_pending_rows(
                    conn=conn,
                    stage=stage,
                    after_id=after_id,
                    fetch_size=current_fetch,
                    statement_timeout_ms=statement_timeout_ms,
                    query_timeout_s=query_timeout_s,
                )
                fetch_ms = round((time.time() - t_fetch0) * 1000, 1)
                logger.info(
                    "[SEQ-STEP%s] fetched=%s after_id=%s fetch_ms=%s",
                    stage, len(rows), after_id, fetch_ms,
                )
            except Exception as e:
                retries_on_fetch += 1
                logger.error(
                    "[SEQ-STEP%s] fetch error after_id=%s size=%s err=%s",
                    stage, after_id, current_fetch, f"{type(e).__name__}:{str(e)[:220]}",
                )
                if current_fetch > 5:
                    fetch_size = max(5, current_fetch // 2)
                    logger.info("[SEQ-STEP%s] reducing fetch_size to %s", stage, fetch_size)
                    await asyncio.sleep(1.0)
                    continue
                raise

            if not rows:
                logger.info("[SEQ-STEP%s] no more pending rows", stage)
                break

            for row in rows:
                cnpj = row["cnpj_basico"]
                website_url = (row.get("website_url") or "").strip()
                raw_content = (row.get("raw_content") or "").strip()
                after_id = max(after_id, int(row["id"]))

                try:
                    if not raw_content:
                        raise ValueError("raw_content vazio")
                    if not website_url:
                        raise ValueError("website_url vazio")

                    if stage == 2:
                        links = extract_subpage_links_from_raw(raw_content, website_url)
                        await db_service.save_scrape_main_subpage_links(
                            cnpj_basico=cnpj,
                            subpage_links=json.dumps(links, ensure_ascii=False),
                            num_subpages=len(links),
                        )
                    else:
                        processed_text = extract_mainpage_text_from_raw(raw_content, website_url)
                        if not processed_text.strip():
                            raise ValueError("texto processado vazio")
                        await db_service.save_scrape_main_processed_text(
                            cnpj_basico=cnpj,
                            mainpage_processada=processed_text,
                        )

                    success += 1
                except Exception as e:
                    errors += 1
                    await db_service.save_scrape_main_error(
                        cnpj_basico=cnpj,
                        error=f"step{stage}:exception:{type(e).__name__}:{str(e)[:300]}",
                        step=stage,
                        website_url=website_url or None,
                    )

                processed += 1
                if sleep_ms > 0:
                    await asyncio.sleep(sleep_ms / 1000.0)

                if processed % progress_every == 0 or processed >= total_samples:
                    elapsed = round(time.time() - started_at, 2)
                    rate = round(processed / elapsed, 2) if elapsed > 0 else 0
                    logger.info(
                        "[SEQ-STEP%s] progress=%s/%s ok=%s err=%s rate=%s rows/s elapsed_s=%s",
                        stage, processed, total_samples, success, errors, rate, elapsed,
                    )

                if processed >= total_samples:
                    break
    finally:
        await conn.close()

    elapsed = round(time.time() - started_at, 2)
    logger.info(
        "[SEQ-STEP%s] done processed=%s ok=%s err=%s retries_fetch=%s elapsed_s=%s",
        stage, processed, success, errors, retries_on_fetch, elapsed,
    )
    return processed, success, errors


async def main():
    parser = argparse.ArgumentParser(description="Runner sequencial para scrape_main etapa 2/3")
    parser.add_argument("--stage", choices=["2", "3", "both"], default="both")
    parser.add_argument("--total-samples", type=int, default=3200)
    parser.add_argument("--fetch-size", type=int, default=50)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--statement-timeout-ms", type=int, default=300000)
    parser.add_argument("--query-timeout-s", type=int, default=180)
    parser.add_argument("--sleep-ms", type=int, default=0)
    parser.add_argument("--log-file", type=str, default="")
    args = parser.parse_args()

    load_dotenv(".env")
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise SystemExit("DATABASE_URL nao encontrada no .env")

    if not args.log_file:
        Path("logs").mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.log_file = f"logs/seq_scrape_main_{stamp}.log"

    logger = setup_logger(args.log_file)
    logger.info("log_file=%s", args.log_file)

    if args.stage in ("2", "both"):
        await process_stage(
            stage=2,
            db_url=db_url,
            total_samples=args.total_samples,
            fetch_size=args.fetch_size,
            progress_every=args.progress_every,
            statement_timeout_ms=args.statement_timeout_ms,
            query_timeout_s=args.query_timeout_s,
            sleep_ms=args.sleep_ms,
            logger=logger,
        )

    if args.stage in ("3", "both"):
        await process_stage(
            stage=3,
            db_url=db_url,
            total_samples=args.total_samples,
            fetch_size=args.fetch_size,
            progress_every=args.progress_every,
            statement_timeout_ms=args.statement_timeout_ms,
            query_timeout_s=args.query_timeout_s,
            sleep_ms=args.sleep_ms,
            logger=logger,
        )


if __name__ == "__main__":
    asyncio.run(main())
