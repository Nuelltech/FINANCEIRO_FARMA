-- Script de Criação de Tabelas para o Pipeline Financeiro Farmácia Piloto
-- Executar no SQL Editor do Supabase

-- 1. Tabela principal de controlo de ficheiros processados
CREATE TABLE IF NOT EXISTS faturas_processadas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drive_file_id TEXT UNIQUE NOT NULL,
    nome_ficheiro_original TEXT NOT NULL,
    nome_ficheiro_novo TEXT,
    fornecedor TEXT,
    farmacia TEXT,
    tipo_documento TEXT,
    numero_documento TEXT,
    data_documento DATE,
    data_vencimento DATE,
    valor_total NUMERIC(10, 2),
    confianca TEXT NOT NULL, -- 'Alta', 'Média', 'Baixa'
    motivo_baixa_confianca TEXT,
    status_processamento TEXT NOT NULL, -- 'PROCESSADO', 'A_REVER', 'DUPLICADO'
    numero_lote_associado TEXT,
    drive_file_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Adicionar coluna se a tabela já existia antes
ALTER TABLE faturas_processadas ADD COLUMN IF NOT EXISTS data_vencimento DATE;

-- 2. Tabela específica para audit e conciliação de Resumos de Lote (Opção B)
CREATE TABLE IF NOT EXISTS resumos_lote (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drive_file_id TEXT NOT NULL,
    numero_lote TEXT NOT NULL,
    fornecedor TEXT NOT NULL,
    farmacia TEXT,
    data_lote DATE,
    valor_total_lote NUMERIC(10, 2),
    lista_faturas_agregadas JSONB, -- Array com [{num_doc: "...", valor: 0.00}]
    soma_faturas_processadas NUMERIC(10, 2) DEFAULT 0.00,
    lote_conciliado BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Índices de alta performance
CREATE INDEX IF NOT EXISTS idx_faturas_doc_forn ON faturas_processadas(numero_documento, fornecedor);
CREATE INDEX IF NOT EXISTS idx_faturas_drive_id ON faturas_processadas(drive_file_id);
CREATE INDEX IF NOT EXISTS idx_resumos_lote_num ON resumos_lote(numero_lote, fornecedor);
