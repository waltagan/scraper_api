#!/usr/bin/env python3
"""
Scraper Optimizer Incremental - Otimização incremental com aprendizado

Este script implementa aprendizado incremental em 4 rodadas para otimizar
os parâmetros do scraper baseado nos resultados de outras_empreas.json.
"""

import asyncio
import time
import logging
import json
import random
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ScraperConfig:
    """Configuração dos parâmetros do scraper"""
    playwright_semaphore: int = 10
    circuit_breaker_threshold: int = 5
    page_timeout: int = 60000
    md_threshold: float = 0.35
    min_word_threshold: int = 5
    chunk_size: int = 3
    chunk_semaphore: int = 30
    session_timeout: int = 15
    max_subpages: int = 100

@dataclass
class ScraperResult:
    """Resultado de um teste do scraper"""
    url: str
    config: ScraperConfig
    duration: float
    text_length: int
    pdf_count: int
    links_count: int
    pages_count: int
    success: bool
    error: str = ""

class ScraperOptimizerIncremental:
    """Otimizador incremental com aprendizado"""

    def __init__(self):
        # Sites selecionados para otimização de velocidade (apenas 3 sites)
        self.test_sites = [
            {
                "empresa": "E2E ENGENHARIA E MONTAGEM LTDA",
                "site": "http://e2e.ind.br/",
                "problema": "otimização de velocidade mantendo qualidade"
            },
            {
                "empresa": "EDJUNIOR ENGENHARIA LTDA",
                "site": "http://edjuniorengenharia.com.br/",
                "problema": "otimização de velocidade mantendo qualidade"
            },
            {
                "empresa": "EL-AM CONSTRUCOES E COMERCIO LTDA",
                "site": "http://elamcoberturas.com/",
                "problema": "otimização de velocidade mantendo qualidade"
            }
        ]

        # Resultados das rodadas
        self.rounds_results: List[List[ScraperResult]] = []
        self.learning_history = []
        self.speed_logs = []  # Logs específicos para velocidade

        # Configuração base otimizada para velocidade (mantendo qualidade)
        self.best_known_config = ScraperConfig(
            playwright_semaphore=30,  # Aumentado para velocidade máxima
            circuit_breaker_threshold=2,  # Mais tolerante para não perder tempo
            page_timeout=15000,  # Muito mais agressivo
            md_threshold=0.6,  # Menos processamento de conteúdo
            min_word_threshold=6,  # Mais permissivo para manter qualidade
            chunk_size=12,  # Processamento mais eficiente
            chunk_semaphore=40,  # Mais paralelismo
            session_timeout=5,  # Ultra rápido
            max_subpages=50  # Menos páginas para velocidade
        )

    def _load_additional_companies(self) -> List[Dict[str, str]]:
        """Carrega a lista adicional de empresas para teste"""
        try:
            with open('outras_empreas.json', 'r', encoding='utf-8') as f:
                companies = json.load(f)

            return [
                {
                    "empresa": company["razao_social"],
                    "site": company["site"],
                    "problema": "teste de otimização incremental"
                }
                for company in companies
            ]
        except Exception as e:
            logger.error(f"Erro ao carregar outras_empreas.json: {e}")
            # Fallback para sites originais se houver problema
            return [
                {
                    "empresa": "DAVI MECANICA DIESEL LTDA",
                    "site": "http://davimecanicadiesel.com.br/",
                    "problema": "não foi selecionado como site do fornecedor"
                },
                {
                    "empresa": "DELTA SOLUCOES EM AUTOMACAO LTDA",
                    "site": "http://deltaaut.com/",
                    "problema": "scrape não coletou nenhuma informação"
                }
            ]

    def calculate_score(self, result: ScraperResult) -> float:
        """Calcula score baseado em performance e qualidade"""
        if not result.success:
            return 0.0

        # Score de qualidade (70% do peso total)
        quality_score = (
            min(result.text_length / 10000, 1.0) * 0.4 +  # Até 10k chars = 40%
            min(result.pdf_count / 10, 1.0) * 0.2 +       # Até 10 PDFs = 20%
            min(result.links_count / 50, 1.0) * 0.2 +     # Até 50 links = 20%
            min(result.pages_count / 20, 1.0) * 0.2       # Até 20 páginas = 20%
        ) * 0.7

        # Score de performance (30% do peso total)
        # Menor tempo = melhor score
        time_score = max(0, 1.0 - (result.duration / 300.0)) * 0.3  # Até 5min = score máximo

        return quality_score + time_score

    def generate_smart_config(self, round_number: int) -> ScraperConfig:
        """
        Gera configuração inteligente focada em VELOCIDADE mantendo QUALIDADE ALTA.
        Cada rodada otimiza diferentes aspectos de performance.
        """
        # Base: Melhor configuração conhecida para velocidade
        base_config = self.best_known_config

        if round_number == 1:
            # Rodada 1: Foco em paralelismo máximo e timeouts agressivos
            return ScraperConfig(
                playwright_semaphore=random.choice([25, 30, 35]),  # Máximo paralelismo
                circuit_breaker_threshold=random.choice([1, 2, 3]),  # Muito tolerante
                page_timeout=random.choice([10000, 15000, 20000]),  # Ultra agressivo
                md_threshold=random.choice([0.5, 0.6, 0.7]),  # Menos processamento
                min_word_threshold=random.choice([5, 6, 7]),  # Qualidade mantida
                chunk_size=random.choice([10, 12, 15]),  # Processamento eficiente
                chunk_semaphore=random.choice([35, 40, 45]),  # Paralelismo alto
                session_timeout=random.choice([3, 5, 7]),  # Sessões ultra rápidas
                max_subpages=random.choice([40, 50, 60])  # Menos páginas
            )

        elif round_number == 2:
            # Rodada 2: Otimizar processamento e reduzir overhead
            return self._generate_speed_config(round_number, "processing")

        elif round_number == 3:
            # Rodada 3: Balanceamento fino entre velocidade e qualidade
            return self._generate_speed_config(round_number, "balanced")

        else:  # round_number == 4
            # Rodada 4: Otimização final baseada em dados empíricos
            return self._generate_speed_config(round_number, "final")

    def _generate_speed_config(self, round_number: int, strategy: str) -> ScraperConfig:
        """Gera configuração otimizada para VELOCIDADE mantendo QUALIDADE ALTA"""

        # Analisar padrões das rodadas anteriores focando em velocidade
        patterns = self._analyze_speed_patterns()

        if strategy == "processing":
            # Foco em processamento paralelo e redução de overhead
            return ScraperConfig(
                playwright_semaphore=min(40, patterns.get('fastest_playwright', 30) + random.choice([0, 5])),
                circuit_breaker_threshold=max(1, patterns.get('fastest_circuit', 2)),
                page_timeout=max(8000, patterns.get('fastest_timeout', 15000) - random.choice([0, 2000])),
                md_threshold=min(0.8, patterns.get('fastest_md', 0.6) + random.choice([0, 0.1])),
                min_word_threshold=max(4, patterns.get('fastest_words', 6) - random.choice([0, 1])),
                chunk_size=min(16, patterns.get('fastest_chunk', 12) + random.choice([0, 3])),
                chunk_semaphore=min(55, patterns.get('fastest_chunk_sem', 40) + random.choice([0, 5])),
                session_timeout=max(2, patterns.get('fastest_session', 5) - random.choice([0, 1])),
                max_subpages=max(30, patterns.get('fastest_pages', 50) - random.choice([0, 10]))
            )

        elif strategy == "balanced":
            # Balanceamento fino: velocidade máxima sem perder qualidade
            return ScraperConfig(
                playwright_semaphore=patterns.get('balanced_playwright', 30),
                circuit_breaker_threshold=patterns.get('balanced_circuit', 2),
                page_timeout=patterns.get('balanced_timeout', 15000),
                md_threshold=round(patterns.get('balanced_md', 0.6), 2),
                min_word_threshold=patterns.get('balanced_words', 6),
                chunk_size=patterns.get('balanced_chunk', 12),
                chunk_semaphore=patterns.get('balanced_chunk_sem', 40),
                session_timeout=patterns.get('balanced_session', 5),
                max_subpages=patterns.get('balanced_pages', 50)
            )

        else:  # final
            # Configuração final baseada em dados empíricos reais
            return ScraperConfig(
                playwright_semaphore=patterns.get('final_playwright', 30),
                circuit_breaker_threshold=patterns.get('final_circuit', 2),
                page_timeout=patterns.get('final_timeout', 15000),
                md_threshold=patterns.get('final_md', 0.6),
                min_word_threshold=patterns.get('final_words', 6),
                chunk_size=patterns.get('final_chunk', 12),
                chunk_semaphore=patterns.get('final_chunk_sem', 40),
                session_timeout=patterns.get('final_session', 5),
                max_subpages=patterns.get('final_pages', 50)
            )

    def _analyze_speed_patterns(self) -> Dict[str, float]:
        """Analisa padrões focados em VELOCIDADE mantendo QUALIDADE ALTA (score > 0.6)"""

        if not self.rounds_results:
            return {}

        patterns = {}
        # Filtrar apenas resultados de alta qualidade (score > 0.6)
        high_quality_results = [
            result for round_results in self.rounds_results
            for result in round_results
            if result.success and self.calculate_score(result) > 0.6
        ]

        if not high_quality_results:
            # Fallback: usar todos os resultados se não houver alta qualidade
            high_quality_results = [
                result for round_results in self.rounds_results
                for result in round_results
                if result.success
            ]

        if not high_quality_results:
            return patterns

        # Agrupar por parâmetro focando em velocidade (menor tempo = melhor)
        param_performance = {
            'playwright_semaphore': [],
            'circuit_breaker_threshold': [],
            'page_timeout': [],
            'md_threshold': [],
            'min_word_threshold': [],
            'chunk_size': [],
            'chunk_semaphore': [],
            'session_timeout': [],
            'max_subpages': []
        }

        for result in high_quality_results:
            config = result.config
            score = self.calculate_score(result)
            speed_score = 1.0 / (1.0 + result.duration)  # Score baseado em velocidade (menor tempo = melhor)

            # Combinar qualidade e velocidade
            combined_score = (score * 0.7) + (speed_score * 0.3)

            param_performance['playwright_semaphore'].append((config.playwright_semaphore, combined_score))
            param_performance['circuit_breaker_threshold'].append((config.circuit_breaker_threshold, combined_score))
            param_performance['page_timeout'].append((config.page_timeout, combined_score))
            param_performance['md_threshold'].append((config.md_threshold, combined_score))
            param_performance['min_word_threshold'].append((config.min_word_threshold, combined_score))
            param_performance['chunk_size'].append((config.chunk_size, combined_score))
            param_performance['chunk_semaphore'].append((config.chunk_semaphore, combined_score))
            param_performance['session_timeout'].append((config.session_timeout, combined_score))
            param_performance['max_subpages'].append((config.max_subpages, combined_score))

        # Encontrar valores que maximizam velocidade mantendo qualidade
        for param, values_scores in param_performance.items():
            if values_scores:
                # Agrupar por valor e calcular score médio combinado
                value_avg_scores = {}
                for value, score in values_scores:
                    if value not in value_avg_scores:
                        value_avg_scores[value] = []
                    value_avg_scores[value].append(score)

                # Calcular médias
                avg_scores = {v: sum(scores)/len(scores) for v, scores in value_avg_scores.items()}

                # Melhor valor para velocidade
                fastest_value = max(avg_scores.items(), key=lambda x: x[1])[0]

                # Estratégias baseadas no parâmetro
                param_key = param.split("_")[-1]
                patterns[f'fastest_{param_key}'] = fastest_value
                patterns[f'balanced_{param_key}'] = fastest_value
                patterns[f'final_{param_key}'] = fastest_value

                # Ajustes específicos para balanceamento
                if param == 'page_timeout':
                    patterns[f'balanced_{param_key}'] = min(fastest_value + 2000, 25000)  # Pouco mais tolerante
                elif param == 'max_subpages':
                    patterns[f'balanced_{param_key}'] = min(fastest_value + 10, 70)  # Poucas páginas a mais
                elif param == 'min_word_threshold':
                    patterns[f'balanced_{param_key}'] = max(fastest_value - 1, 5)  # Manter qualidade

        return patterns

    async def test_config_on_sites(self, config: ScraperConfig) -> List[ScraperResult]:
        """Testa uma configuração em todos os sites com logs detalhados de velocidade"""
        results = []

        # Modificar dinamicamente os parâmetros do scraper
        await self._apply_config_to_scraper(config)

        for site_info in self.test_sites:
            site_start_time = time.time()
            site_log = {
                "site": site_info['site'],
                "empresa": site_info['empresa'],
                "config": {
                    "playwright_semaphore": config.playwright_semaphore,
                    "page_timeout": config.page_timeout,
                    "chunk_size": config.chunk_size,
                    "session_timeout": config.session_timeout,
                    "max_subpages": config.max_subpages
                },
                "start_time": site_start_time,
                "end_time": None,
                "duration": None,
                "success": False,
                "error": None,
                "performance_metrics": {}
            }

            try:
                logger.info(f"🚀 [SPEED TEST] Iniciando scrape de {site_info['empresa']} - {site_info['site']}")
                logger.info(f"⚡ [SPEED TEST] Config: semaphore={config.playwright_semaphore}, timeout={config.page_timeout}ms, chunk={config.chunk_size}")

                # Importar e usar o scraper com timeout otimizado para velocidade
                from app.services.scraper import scrape_url

                scrape_start = time.time()
                text, pdfs, visited_urls = await asyncio.wait_for(
                    scrape_url(site_info['site'], config.max_subpages),
                    timeout=300  # 5 minutos máximo por site (otimizado para velocidade)
                )
                scrape_duration = time.time() - scrape_start

                result = ScraperResult(
                    url=site_info['site'],
                    config=config,
                    duration=scrape_duration,
                    text_length=len(text),
                    pdf_count=len(pdfs),
                    links_count=len(visited_urls),
                    pages_count=len(visited_urls),
                    success=True
                )

                # Calcular métricas de performance
                quality_score = self.calculate_score(result)
                chars_per_second = len(text) / scrape_duration if scrape_duration > 0 else 0
                pages_per_second = len(visited_urls) / scrape_duration if scrape_duration > 0 else 0

                site_log.update({
                    "end_time": time.time(),
                    "duration": scrape_duration,
                    "success": True,
                    "performance_metrics": {
                        "text_length": len(text),
                        "pdf_count": len(pdfs),
                        "pages_count": len(visited_urls),
                        "quality_score": quality_score,
                        "chars_per_second": chars_per_second,
                        "pages_per_second": pages_per_second,
                        "efficiency_ratio": quality_score / scrape_duration if scrape_duration > 0 else 0
                    }
                })

                logger.info(".2f")
                logger.info(".1f")
                logger.info(".2f")
                logger.info(".3f")
                self.speed_logs.append(site_log)

            except asyncio.TimeoutError:
                error_msg = f"Site {site_info['site']} excedeu timeout de 5 minutos"
                logger.warning(f"⏰ [SPEED TEST] {error_msg}")
                result = ScraperResult(
                    url=site_info['site'],
                    config=config,
                    duration=300,  # Tempo máximo
                    text_length=0,
                    pdf_count=0,
                    links_count=0,
                    pages_count=0,
                    success=False,
                    error=error_msg
                )
                site_log.update({"success": False, "error": error_msg})
                self.speed_logs.append(site_log)

            except Exception as e:
                error_msg = f"Erro ao testar {site_info['site']}: {str(e)}"
                logger.error(f"❌ [SPEED TEST] {error_msg}")
                result = ScraperResult(
                    url=site_info['site'],
                    config=config,
                    duration=time.time() - site_start_time,
                    text_length=0,
                    pdf_count=0,
                    links_count=0,
                    pages_count=0,
                    success=False,
                    error=str(e)
                )
                site_log.update({"success": False, "error": str(e)})
                self.speed_logs.append(site_log)

            results.append(result)

        return results

    async def _apply_config_to_scraper(self, config: ScraperConfig):
        """Aplica configuração ao módulo scraper dinamicamente"""
        from app.services.scraper import configure_scraper_params

        # Usar a função de configuração do próprio scraper
        configure_scraper_params(
            playwright_semaphore_limit=config.playwright_semaphore,
            circuit_breaker_threshold=config.circuit_breaker_threshold,
            page_timeout=config.page_timeout,
            md_threshold=config.md_threshold,
            min_word_threshold=config.min_word_threshold,
            chunk_size=config.chunk_size,
            chunk_semaphore_limit=config.chunk_semaphore,
            session_timeout=config.session_timeout
        )

    async def optimize_incremental(self, rounds: int = 4):
        """
        Executa otimização incremental focada em VELOCIDADE com 3 sites.
        Cada rodada testa uma configuração otimizada para velocidade.
        """
        logger.info("🚀 Iniciando otimização de VELOCIDADE do scraper...")
        logger.info(f"📊 Executando {rounds} rodadas focadas em velocidade")
        logger.info(f"🏢 Testando {len(self.test_sites)} empresas selecionadas")
        logger.info("🎯 Prioridade: VELOCIDADE MÁXIMA mantendo QUALIDADE > 0.6")

        overall_best_score = 0.0
        overall_best_config = None

        for round_num in range(1, rounds + 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"🎯 RODADA {round_num}/{rounds} - APRENDIZADO INCREMENTAL")
            logger.info(f"{'='*60}")

            round_results = []
            round_scores = []

            logger.info(f"🔄 Executando teste único da Rodada {round_num}")

            # Gerar configuração inteligente baseada no aprendizado
            config = self.generate_smart_config(round_num)

            # Log da estratégia usada
            if round_num == 1:
                strategy = "Paralelismo máximo + timeouts agressivos"
            elif round_num == 2:
                strategy = "Processamento otimizado + redução de overhead"
            elif round_num == 3:
                strategy = "Balanceamento fino velocidade/qualidade"
            else:
                strategy = "Otimização final baseada em dados empíricos"

            logger.info(f"🎯 Estratégia: {strategy}")
            logger.info("⚡ CONFIGURAÇÃO FOCADA EM VELOCIDADE:")
            logger.info(f"   playwright_semaphore: {config.playwright_semaphore} (paralelismo)")
            logger.info(f"   page_timeout: {config.page_timeout}ms (agressivo)")
            logger.info(f"   chunk_size: {config.chunk_size} (processamento eficiente)")
            logger.info(f"   session_timeout: {config.session_timeout}s (sessões rápidas)")
            logger.info(f"   max_subpages: {config.max_subpages} (foco)")
            logger.info(f"   circuit_breaker_threshold: {config.circuit_breaker_threshold}")
            logger.info(f"   md_threshold: {config.md_threshold}")
            logger.info(f"   min_word_threshold: {config.min_word_threshold}")
            logger.info(f"   chunk_semaphore: {config.chunk_semaphore}")

            # Testar configuração em todos os sites
            try:
                test_results = await self.test_config_on_sites(config)
                round_results.extend(test_results)

                # Calcular métricas do teste
                successful_results = [r for r in test_results if r.success]
                failed_sites = [r for r in test_results if not r.success]

                if successful_results:
                    avg_score = sum(self.calculate_score(r) for r in successful_results) / len(successful_results)
                    round_scores.append(avg_score)

                    # Calcular métricas de velocidade agregadas
                    avg_duration = sum(r.duration for r in successful_results) / len(successful_results)
                    total_chars = sum(r.text_length for r in successful_results)
                    total_pages = sum(r.pages_count for r in successful_results)

                    logger.info(".3f")
                    logger.info(".2f")
                    logger.info(".1f")
                    logger.info(f"   Sucessos: {len(successful_results)}/{len(self.test_sites)}")

                    # Atualizar melhor configuração geral
                    if avg_score > overall_best_score:
                        overall_best_score = avg_score
                        overall_best_config = config
                        logger.info("   🏆 NOVA MELHOR CONFIGURAÇÃO GERAL ENCONTRADA!")

                # Avisar sobre sites que falharam
                if failed_sites:
                    logger.warning("   ⚠️ SITES QUE NÃO FORAM SCRAPADOS:")
                    for failed in failed_sites:
                        logger.warning(f"      ❌ {failed.url}: {failed.error}")

            except Exception as e:
                logger.error(f"Erro na rodada {round_num}: {e}")

            # Resultado da rodada
            self.rounds_results.append(round_results)

            if round_scores:
                avg_round_score = sum(round_scores) / len(round_scores)
                logger.info(f"\n📊 RESULTADO DA RODADA {round_num}:")
                logger.info(f"   Score médio da rodada: {avg_round_score:.3f}")
                logger.info(f"   Score médio: {avg_round_score:.3f}")
                logger.info(f"   Total de testes: {len(round_scores)}")
                logger.info(f"   Sucessos na rodada: {sum(1 for r in round_results if r.success)}/{len(round_results)}")

                # Aprendizado: analisar padrões desta rodada
                self._learn_from_round(round_num, round_results)
            else:
                logger.warning(f"Rodada {round_num} não teve testes bem-sucedidos")

        # Resultado final
        logger.info(f"\n{'='*70}")
        logger.info("🏁 OTIMIZAÇÃO INCREMENTAL CONCLUÍDA")
        logger.info(f"{'='*70}")

        if overall_best_config:
            logger.info("🎯 MELHOR CONFIGURAÇÃO FINAL ENCONTRADA:")
            logger.info(f"   Score: {overall_best_score:.3f}")
            logger.info(f"   playwright_semaphore: {overall_best_config.playwright_semaphore}")
            logger.info(f"   circuit_breaker_threshold: {overall_best_config.circuit_breaker_threshold}")
            logger.info(f"   page_timeout: {overall_best_config.page_timeout}")
            logger.info(f"   md_threshold: {overall_best_config.md_threshold}")
            logger.info(f"   min_word_threshold: {overall_best_config.min_word_threshold}")
            logger.info(f"   chunk_size: {overall_best_config.chunk_size}")
            logger.info(f"   chunk_semaphore: {overall_best_config.chunk_semaphore}")
            logger.info(f"   session_timeout: {overall_best_config.session_timeout}")
            logger.info(f"   max_subpages: {overall_best_config.max_subpages}")

            # Salvar melhor configuração
            self._save_best_config_incremental(overall_best_config, overall_best_score)

        # Estatísticas finais
        total_tests = sum(len(round_results) for round_results in self.rounds_results)
        successful_tests = sum(1 for round_results in self.rounds_results for r in round_results if r.success)
        success_rate = (successful_tests / total_tests) * 100 if total_tests > 0 else 0

        logger.info("\n📈 ESTATÍSTICAS FINAIS:")
        logger.info(f"   Total de testes: {total_tests}")
        logger.info(f"   Testes bem-sucedidos: {successful_tests}")
        logger.info(f"   Taxa de sucesso: {success_rate:.1f}%")
        logger.info(f"   Rodadas executadas: {len(self.rounds_results)}")

        # Salvar todos os resultados
        self._save_incremental_results()

        return overall_best_config, overall_best_score

    def _learn_from_round(self, round_num: int, round_results: List[ScraperResult]):
        """Aprende com os resultados da rodada atual"""

        successful_results = [r for r in round_results if r.success]
        if not successful_results:
            return

        # Calcular estatísticas por parâmetro
        param_stats = {}

        for result in successful_results:
            config = result.config
            score = self.calculate_score(result)

            # Coletar estatísticas
            params = {
                'playwright_semaphore': config.playwright_semaphore,
                'circuit_breaker_threshold': config.circuit_breaker_threshold,
                'page_timeout': config.page_timeout,
                'md_threshold': config.md_threshold,
                'min_word_threshold': config.min_word_threshold,
                'chunk_size': config.chunk_size,
                'chunk_semaphore': config.chunk_semaphore,
                'session_timeout': config.session_timeout,
                'max_subpages': config.max_subpages
            }

            for param_name, param_value in params.items():
                if param_name not in param_stats:
                    param_stats[param_name] = {}
                if param_value not in param_stats[param_name]:
                    param_stats[param_name][param_value] = []
                param_stats[param_name][param_value].append(score)

        # Extrair aprendizados
        learnings = {}
        for param_name, value_scores in param_stats.items():
            # Encontrar melhor valor para este parâmetro
            best_value = None
            best_avg_score = 0

            for value, scores in value_scores.items():
                avg_score = sum(scores) / len(scores)
                if avg_score > best_avg_score:
                    best_avg_score = avg_score
                    best_value = value

            learnings[param_name] = {
                'best_value': best_value,
                'best_score': best_avg_score,
                'total_samples': sum(len(scores) for scores in value_scores.values())
            }

        # Registrar aprendizado
        learning_record = {
            'round': round_num,
            'learnings': learnings,
            'round_stats': {
                'total_results': len(round_results),
                'successful_results': len(successful_results),
                'avg_score': sum(self.calculate_score(r) for r in successful_results) / len(successful_results) if successful_results else 0
            }
        }

        self.learning_history.append(learning_record)

        logger.info(f"🧠 APRENDIZADO DA RODADA {round_num}:")
        for param, stats in learnings.items():
            logger.info(f"   {param}: melhor={stats['best_value']} (score={stats['best_score']:.3f}, amostras={stats['total_samples']})")

    def _save_best_config_incremental(self, config: ScraperConfig, score: float):
        """Salva a melhor configuração da otimização incremental"""
        best_config_data = {
            "score": score,
            "config": {
                "playwright_semaphore": config.playwright_semaphore,
                "circuit_breaker_threshold": config.circuit_breaker_threshold,
                "page_timeout": config.page_timeout,
                "md_threshold": config.md_threshold,
                "min_word_threshold": config.min_word_threshold,
                "chunk_size": config.chunk_size,
                "chunk_semaphore": config.chunk_semaphore,
                "session_timeout": config.session_timeout,
                "max_subpages": config.max_subpages
            },
            "optimization_type": "incremental_learning",
            "rounds_executed": len(self.rounds_results),
            "companies_tested": len(self.test_sites),
            "timestamp": time.time()
        }

        with open("best_scraper_config_incremental.json", "w", encoding="utf-8") as f:
            json.dump(best_config_data, f, indent=2, ensure_ascii=False)

        logger.info("💾 Melhor configuração incremental salva em best_scraper_config_incremental.json")

    def _save_incremental_results(self):
        """Salva todos os resultados da otimização incremental"""
        results_data = {
            "rounds": [],
            "learning_history": self.learning_history,
            "speed_logs": self.speed_logs,
            "summary": {
                "total_rounds": len(self.rounds_results),
                "total_tests": sum(len(r) for r in self.rounds_results),
                "total_successes": sum(1 for r in self.rounds_results for res in r if res.success),
                "companies_tested": len(self.test_sites),
                "optimization_type": "speed_optimization",
                "focus": "maximum_speed_with_quality_above_0.6"
            }
        }

        for i, round_results in enumerate(self.rounds_results):
            round_data = []
            for result in round_results:
                round_data.append({
                    "url": result.url,
                    "config": {
                        "playwright_semaphore": result.config.playwright_semaphore,
                        "circuit_breaker_threshold": result.config.circuit_breaker_threshold,
                        "page_timeout": result.config.page_timeout,
                        "md_threshold": result.config.md_threshold,
                        "min_word_threshold": result.config.min_word_threshold,
                        "chunk_size": result.config.chunk_size,
                        "chunk_semaphore": result.config.chunk_semaphore,
                        "session_timeout": result.config.session_timeout,
                        "max_subpages": result.config.max_subpages
                    },
                    "duration": result.duration,
                    "text_length": result.text_length,
                    "pdf_count": result.pdf_count,
                    "links_count": result.links_count,
                    "pages_count": result.pages_count,
                    "success": result.success,
                    "error": result.error,
                    "score": self.calculate_score(result)
                })

            results_data["rounds"].append({
                "round_number": i + 1,
                "results": round_data
            })

        with open("scraper_incremental_results.json", "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)

        logger.info("💾 Todos os resultados incrementais salvos em scraper_incremental_results.json")

async def main():
    """Função principal - Otimização de velocidade para 3 sites"""
    optimizer = ScraperOptimizerIncremental()
    await optimizer.optimize_incremental(rounds=4)

if __name__ == "__main__":
    asyncio.run(main())
