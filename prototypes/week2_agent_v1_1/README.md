# Week 2 AI Agent V1.1 contract prototype

> **PROTOTYPE / NOT PRODUCTION**

This directory is a local Week 2 validation aid. It is not connected to the
FastAPI application, the legacy Agent routes, a language model, or any
external service.

The prototype only:

- constrains tool and task-status names;
- parses the existing RPA success/error envelopes;
- classifies business findings separately from technical failures;
- applies the V1.1 one-retry rule and stable `operation_id` rule; and
- derives a terminal validation status from already returned tool results.

It does not execute a model, execute arbitrary scripts, persist human
confirmation, edit source files, or decide whether `record_not_found` should
be archived to OA.
