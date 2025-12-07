# Request for Comments (RFC) Template

This template demonstrates the structure expected by the Documentation Backfill tool. The tool automatically extracts these sections from Confluence pages or other sources.

## Document Information

**Title:** [Technical Feature/Change Name]  
**Status:** [Draft/Review/Approved]  
**Owner:** [Technical Lead Name]  
**Authors:** [Author 1, Author 2]  
**Date:** [YYYY-MM-DD]

---

## 1. Overview

**Overview ID:** Overview

Provide a high-level summary of the proposed technical change or feature.

**Example:**
This RFC proposes implementing [feature/change] to address [problem/need]. The solution involves [brief description of approach].

### Success Criteria

**Success Criteria ID:** Success-Criteria

Define measurable technical success metrics.

**Example:**
- System performance: [metric] improves by [X]%
- Reliability: Uptime target of [X]%
- Scalability: Support [X] concurrent users
- Code quality: Test coverage > [X]%

### Out of Scope

**Out of Scope ID:** Out-of-Scope

Clearly define what is NOT included in this RFC.

**Example:**
- Feature X (covered in separate RFC)
- Mobile app changes
- Legacy system migration

### Related Documents

**Related Documents ID:** Related-Documents

Links to related RFCs, PRDs, or technical documentation.

**Example:**
- Related PRD: [URL]
- Dependent RFC: [URL]
- API documentation: [URL]

### Assumptions

**Assumptions ID:** Assumptions

List any assumptions made in this design.

**Example:**
- Assumes existing infrastructure can support [requirement]
- Assumes [dependency] will be available by [date]
- Assumes user base will not exceed [limit]

### Dependencies

**Dependencies ID:** Dependencies

List external dependencies or prerequisites.

**Example:**
- Requires API version 2.0
- Depends on database migration completion
- Requires third-party service integration

---

## 2. Technical Design

**Technical Design ID:** Technical-Design

Detailed technical design and implementation approach.

### Architecture & Tech Stack

**Architecture & Tech Stack ID:** Architecture-&-Tech-Stack

Describe the system architecture and technology choices.

**Example:**
- **Backend:** Python 3.10+, FastAPI
- **Database:** PostgreSQL 14+
- **Cache:** Redis 6+
- **Message Queue:** RabbitMQ
- **Deployment:** Docker, Kubernetes

**Architecture Diagram:**
[Link to diagram or describe architecture]

### Sequence

**Sequence ID:** Sequence

Describe the sequence of operations or data flow.

**Example:**
1. User initiates request
2. API validates input
3. Service processes business logic
4. Database transaction commits
5. Response returned to user

### Database Model

**Database Model ID:** Database-Model

Describe database schema changes, new tables, or data models.

**Example:**
```sql
CREATE TABLE example_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### APIs

**APIs ID:** APIs

Document new or modified API endpoints.

**Example:**
- `POST /api/v1/example` - Create new resource
- `GET /api/v1/example/{id}` - Retrieve resource
- `PUT /api/v1/example/{id}` - Update resource
- `DELETE /api/v1/example/{id}` - Delete resource

---

## 3. High Availability & Security

**High Availability & Security ID:** High-Availability-&-Security

Address reliability, availability, and security considerations.

### Performance Requirements

**Performance Requirements ID:** Performance-Requirements

Define performance targets and requirements.

**Example:**
- API response time: < 200ms (p95)
- Database query time: < 50ms (p95)
- Throughput: 1000 requests/second
- Concurrent users: 10,000+

### Monitoring & Alerting

**Monitoring & Alerting ID:** Monitoring-&-Alerting

Describe monitoring, metrics, and alerting strategy.

**Example:**
- Key metrics: Request rate, error rate, latency
- Alerts: Error rate > 1%, latency p95 > 500ms
- Dashboards: [Link to Grafana/Datadog dashboard]
- Log aggregation: [Tool/Service]

### Logging

**Logging ID:** Logging

Describe logging strategy and requirements.

**Example:**
- Log levels: INFO, WARNING, ERROR
- Structured logging: JSON format
- Log retention: 30 days
- Sensitive data: Never log passwords, tokens, or PII

### Security Implications

**Security Implications ID:** Security-Implications

Address security considerations and requirements.

**Example:**
- Authentication: OAuth 2.0 required
- Authorization: Role-based access control
- Data encryption: TLS in transit, AES-256 at rest
- Input validation: All inputs sanitized
- Rate limiting: 100 requests/minute per user

---

## 4. Backwards Compatibility & Rollout Plan

**Backwards Compatibility & Rollout Plan ID:** Backwards-Compatibility-&-Rollout-Plan

Address compatibility and deployment strategy.

### Compatibility

**Compatibility ID:** Compatibility

Describe backwards compatibility considerations.

**Example:**
- API versioning: Maintains v1 compatibility
- Database migrations: Backwards compatible schema changes
- Feature flags: Gradual rollout capability
- Deprecation: 6-month notice for breaking changes

### Rollout Strategy

**Rollout Strategy ID:** Rollout-Strategy

Describe the deployment and rollout plan.

**Example:**
1. **Phase 1 (Week 1):** Internal testing, 10% traffic
2. **Phase 2 (Week 2):** Beta users, 25% traffic
3. **Phase 3 (Week 3):** General availability, 100% traffic
4. **Rollback plan:** Feature flag disable, database rollback script

---

## 5. Concerns, Questions, or Known Limitations

**Concerns, Questions, or Known Limitations ID:** Concerns-Questions-Known-Limitations

Document any concerns, open questions, or known limitations.

**Example:**
- **Concern:** High database load during peak hours
  - **Mitigation:** Implement caching layer
- **Question:** Should we support batch operations?
  - **Decision:** Defer to future RFC
- **Limitation:** Maximum 1000 items per request
  - **Reason:** Performance constraints

---

## Additional Sections

### Alternatives Considered

**Alternatives Considered ID:** Alternatives-Considered

Document alternative approaches that were considered.

**Example:**
1. **Alternative A:** [Description]
   - Pros: [List]
   - Cons: [List]
   - Why not chosen: [Reason]

2. **Alternative B:** [Description]
   - [Similar format]

### Risks & Mitigations

**Risks & Mitigations ID:** Risks-&-Mitigations

Identify risks and mitigation strategies.

**Example:**
- **Risk:** Database performance degradation
  - **Likelihood:** Medium
  - **Impact:** High
  - **Mitigation:** Database indexing, query optimization, monitoring

### Testing Strategy

**Testing Strategy ID:** Testing-Strategy

Describe testing approach and requirements.

**Example:**
- Unit tests: > 80% coverage
- Integration tests: Critical paths
- Load testing: Simulate 10K concurrent users
- Security testing: Penetration testing required

### Timeline

**Timeline ID:** Timeline

Provide estimated timeline and milestones.

**Example:**
- Design review: Week 1
- Implementation: Weeks 2-4
- Testing: Week 5
- Deployment: Week 6

---

## Notes

- This template uses Confluence heading IDs (e.g., `id="Overview"`) for optimal extraction
- The tool can also extract content using heading text patterns (e.g., "1. Overview", "Overview")
- All sections are optional, but more sections provide better context for description generation
- Use clear, descriptive headings to ensure proper extraction
- For Confluence, use proper heading hierarchy (H1, H2, H3) for best results

