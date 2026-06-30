# AI Document Processing Pipeline

## Overview

An enterprise-oriented, audit-ready intelligent document processing
platform that transforms unstructured business documents into
standardized, validated and reviewable records.

The system combines deterministic parsing, configurable document
templates, AI-assisted extraction, validation, asynchronous processing
and human review. AI assists reviewers---it never replaces business
rules or human approval.

------------------------------------------------------------------------

# Key Features

-   Asynchronous processing using FastAPI, Celery and Redis
-   PostgreSQL as the system of record
-   Original file preservation and download
-   Auto Detect document mode
-   Free Extraction mode (template-free AI extraction)
-   Configurable template-based extraction
-   Deterministic template-labelled extraction
-   Provider-agnostic AI (Gemini, Claude, Ollama, Mock,
    OpenAI-compatible)
-   AI Review Assistant
-   Validation engine
-   Human review workflow
-   Source highlighting and document preview
-   Audit trail
-   Automatic Celery recovery workflows
-   Dashboard and searchable database records

------------------------------------------------------------------------

# Processing Modes

## Auto Detect (Recommended)

Automatically classifies the uploaded document and applies the most
suitable template. If no suitable template is found, processing falls
back to Free Extraction.

## Free Extraction

Processes the uploaded document without using any predefined template.
The parser and AI determine useful fields automatically.

## Template Mode

Uses a selected company template to extract standardized fields. Missing
required fields are automatically created for review.

------------------------------------------------------------------------

# Processing Pipeline

``` text
Upload
│
├── Store original file
├── Create processing job
│
▼
Celery Worker
│
├── Parse document
├── Deterministic template-labelled extraction
├── AI extraction (when required)
├── Template enforcement
├── Validation engine
├── AI Review Assistant
│
▼
Human Review
│
├── Accept
├── Correct
├── Add fields
├── Remove custom fields
├── Reject
│
▼
Approved Audit-Ready Record
```

------------------------------------------------------------------------

# AI Responsibilities

The AI is used to:

-   Classify document types
-   Extract structured fields
-   Assist Free Extraction
-   Estimate confidence
-   Explain extracted data
-   Produce AI Review Assistant summaries
-   Highlight potential inconsistencies

The AI **does not**:

-   Approve documents
-   Reject documents
-   Modify approved data automatically
-   Override validation rules

------------------------------------------------------------------------

# Validation

Every extracted field is validated using deterministic rules including:

-   Required fields
-   Dates
-   Email addresses
-   Numeric values
-   Currency
-   Currency codes
-   Percentages
-   Regex-based validation

Fields below the confidence threshold or failing validation require
review.

------------------------------------------------------------------------

# Review Workspace

The review interface provides:

-   Extraction Information
-   AI Review Assistant summary
-   Original document preview
-   Source highlighting
-   Confidence indicators
-   Validation messages
-   Audit timeline
-   Original file download

------------------------------------------------------------------------

# Database

## PostgreSQL

Stores:

-   Documents
-   Original uploaded files
-   Parsed text
-   Extracted fields
-   Review decisions
-   AI review summaries
-   Processing jobs
-   Audit logs

## Redis

Used only as the Celery message broker.

------------------------------------------------------------------------

# Background Processing

Celery performs:

-   Document processing
-   AI extraction
-   AI review generation
-   Retry of deferred AI jobs
-   Recovery of stalled jobs
-   Requeueing orphaned pending jobs

Celery Beat schedules automatic recovery tasks.

------------------------------------------------------------------------

# Technology Stack

## Backend

-   Python
-   FastAPI
-   SQLAlchemy
-   Celery
-   uv

## Frontend

-   Next.js
-   React
-   TypeScript
-   Tailwind CSS

## Infrastructure

-   PostgreSQL
-   Redis
-   Docker
-   Docker Compose

------------------------------------------------------------------------

# Sample Templates

Finance

-   Invoice
-   Bank Statement

Construction

-   Purchase Order
-   Progress Claim

Templates define standardized business fields and validation rules while
allowing AI to populate missing information where appropriate.

------------------------------------------------------------------------

# Project Scope

This MVP demonstrates:

-   Enterprise document ingestion
-   AI-assisted extraction
-   Configurable document templates
-   Human-in-the-loop review
-   Validation
-   Auditability
-   Asynchronous processing
-   Provider-agnostic AI architecture

It is intentionally **not** a reporting platform, chatbot or RAG system.

------------------------------------------------------------------------

# Future Enhancements

Potential future work includes:

-   OCR for scanned documents
-   RAG-powered knowledge assistant
-   Semantic search
-   ERP/CRM integrations
-   Authentication and role-based access control
-   Template management UI
-   Analytics and reporting

------------------------------------------------------------------------