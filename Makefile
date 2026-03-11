.PHONY: test test-cov test-watch install-dev clean help

help:
	@echo "Comandos disponíveis:"
	@echo "  make install-dev  - Instalar dependências de desenvolvimento"
	@echo "  make test         - Executar todos os testes"
	@echo "  make test-cov     - Executar testes com relatório de cobertura"
	@echo "  make test-watch   - Executar testes em modo watch (auto-reload)"
	@echo "  make clean        - Limpar cache e arquivos temporários"

install-dev:
	@echo "Instalando dependências de desenvolvimento..."
	pip install -r requirements-dev.txt
	@echo "✅ Dependências instaladas!"

test:
	@echo "Executando testes..."
	pytest
	@echo "✅ Testes concluídos!"

test-cov:
	@echo "Executando testes com cobertura..."
	pytest --cov=agents --cov=services --cov-report=html --cov-report=term-missing
	@echo "✅ Relatório de cobertura gerado em htmlcov/index.html"

test-watch:
	@echo "Executando testes em modo watch..."
	pytest-watch

clean:
	@echo "Limpando cache e arquivos temporários..."
	rm -rf .pytest_cache htmlcov .coverage __pycache__ */__pycache__ */*/__pycache__
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "✅ Limpeza concluída!"