# DevLens

**AI-Powered Code Review and Skill Gap Analyzer**

## Overview

DevLens is a full-stack developer tool that fetches public GitHub repositories and
analyzes repository source code using an AI-powered backend. It is designed to help
developers understand code quality, spot skill gaps, and receive concrete improvement
recommendations from a single structured workflow.

## Technologies

- React
- Node.js
- Express
- GitHub REST API
- AI

## Features

- Fetches public GitHub repositories for analysis.
- Analyzes repository source code using an AI-powered backend.
- Supports code-quality scoring.
- Supports skill-gap analysis.
- Generates improvement recommendations.
- Supports analysis history.
- Supports shareable reports.

## Engineering Contributions

- Designed the client-server architecture for repository processing.
- Implements rate limiting for responsible use of external services.
- Uses structured API workflows between the React frontend and the Express backend.
- Focuses on reliability across the repository fetch, analysis, and report flow.

## Reliability and Security Considerations

- Focuses on reliability and responsible use of external services, including rate
  limiting on outbound GitHub API usage.
- Keeps the integration surface structured: the frontend consumes documented API
  routes rather than ad-hoc calls.
- Treats external repository data as untrusted input that is processed by the
  backend before results are presented.

## Interview Explanation

DevLens demonstrates end-to-end client-server design: a React client requests
analysis through structured API endpoints, an Express backend fetches public
repositories through the GitHub REST API, and an AI-powered layer produces
code-quality scores, skill-gap analysis, and improvement recommendations. The
implementation covers rate limiting, analysis history, and shareable reports,
which makes it a useful example for discussing API integration, reliability, and
responsible use of external services.
