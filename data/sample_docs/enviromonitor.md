# EnviroMonitor

**AQI Reporting and Monitoring Platform**

## Overview

EnviroMonitor is a full-stack environmental monitoring platform that supports
submission of environmental readings, computes AQI, and generates compliant
reports. It integrates backend services with the application workflow to provide
a consistent data-driven user experience.

## Technologies

- Node.js
- Express
- MySQL
- REST APIs

## Features

- Supports submission of environmental readings.
- Computes AQI from submitted readings.
- Generates compliant reports.
- Implements authentication safeguards.
- Includes a health-check endpoint.
- Provides a consistent data-driven user experience.

## Backend Contributions

- Built REST API routes on Node.js and Express for reading submission and report
  generation.
- Integrates backend services with the application workflow so the frontend works
  against a stable, structured API.
- Includes a health-check endpoint for verifying that the service is running.

## Database Contributions

- Uses MySQL as the relational data store for environmental readings and reports.
- Includes database migration scripts so schema setup is reproducible.
- Uses SQL for structured query and reporting needs.

## Reliability and Testing Practices

- Includes linting to keep the codebase consistent.
- Includes smoke tests to verify the service starts and responds.
- Implements authentication safeguards around the data-submission workflow.
- Uses a health-check endpoint to support operational monitoring.
