# OPI Architecture Diagram

## High-Level OPI Flow

```mermaid
graph TD
    A[Block Ingestion] --> B[Transaction Parsing]
    B --> C{OPI Router}
    C -->|op: "swap"| D[OPI-1 Processor]
    C -->|op: "no_return"| E[OPI-0 Processor]
    C -->|op: "deploy"| F[Legacy BRC20 Processor]
    D --> G[State Validation]
    E --> G
    F --> G
    G --> H[Atomic Commit]
    H --> I[Database Update]
```

## OPI Component Architecture

```mermaid
graph TB
    subgraph "OPI Framework"
        A[OPI Registry] --> B[Base Processor Interface]
        B --> C[OPI-0 Processor]
        B --> D[OPI-1 Processor]
        B --> E[Custom OPI Processor]
    end
    
    subgraph "State Management"
        F[Context] --> G[Intermediate State]
        G --> H[State Update Commands]
        H --> I[Atomic State Changes]
    end
    
    subgraph "Core Indexer"
        J[Block Parser] --> K[OPI Router]
        K --> A
        A --> F
        I --> L[Database]
    end
```

## OPI Development Workflow

```mermaid
graph LR
    A[Create OPI Module] --> B[Implement BaseProcessor]
    B --> C[Define Data Contracts]
    C --> D[Write Tests]
    D --> E[Register OPI]
    E --> F[Test Integration]
    F --> G[Deploy to Production]
    
    H[Code Review] --> I[Security Audit]
    I --> J[Performance Testing]
    J --> K[Documentation Review]
    K --> G
```

## State Management Flow

```mermaid
sequenceDiagram
    participant T as Transaction
    participant P as Parser
    participant R as OPI Router
    participant OP as OPI Processor
    participant C as Context
    participant IS as Intermediate State
    participant DB as Database
    
    T->>P: Raw Transaction Data
    P->>R: Parsed Operation
    R->>OP: Route to Processor
    OP->>C: Read Current State
    C->>IS: Get Intermediate State
    OP->>OP: Process Operation
    OP->>IS: Update Intermediate State
    IS->>DB: Atomic Commit
    DB-->>OP: Confirmation
```

## OPI Testing Architecture

```mermaid
graph TB
    subgraph "Test Suite"
        A[Unit Tests] --> B[OPI Processor Tests]
        A --> C[Contract Tests]
        A --> D[State Management Tests]
        
        E[Integration Tests] --> F[End-to-End Tests]
        E --> G[Database Integration Tests]
        E --> H[API Integration Tests]
        
        I[Functional Tests] --> J[Workflow Tests]
        I --> K[Performance Tests]
        I --> L[Security Tests]
    end
    
    M[Test Runner] --> A
    M --> E
    M --> I
```

## Deployment Architecture

```mermaid
graph TB
    subgraph "Development"
        A[Local Development] --> B[Unit Tests]
        B --> C[Integration Tests]
    end
    
    subgraph "Staging"
        D[Staging Environment] --> E[Full Test Suite]
        E --> F[Performance Tests]
        F --> G[Security Tests]
    end
    
    subgraph "Production"
        H[Blue Environment] --> I[Health Checks]
        J[Green Environment] --> K[Health Checks]
        I --> L[Traffic Switch]
        K --> L
    end
    
    C --> D
    G --> H
    G --> J
```

## Monitoring and Observability

```mermaid
graph TB
    subgraph "OPI Monitoring"
        A[Metrics Collection] --> B[Performance Metrics]
        A --> C[Error Metrics]
        A --> D[State Metrics]
        
        E[Logging] --> F[Structured Logs]
        F --> G[Log Aggregation]
        
        H[Alerting] --> I[Performance Alerts]
        H --> J[Error Alerts]
        H --> K[Security Alerts]
    end
    
    L[OPI Processors] --> A
    L --> E
    M[Monitoring Dashboard] --> B
    M --> C
    M --> D
```

## Security Architecture

```mermaid
graph TB
    subgraph "Security Layers"
        A[Input Validation] --> B[Operation Validation]
        B --> C[State Validation]
        C --> D[Access Control]
        
        E[Security Monitoring] --> F[Anomaly Detection]
        F --> G[Threat Detection]
        G --> H[Incident Response]
    end
    
    I[OPI Operations] --> A
    J[Security Events] --> E
    K[Security Dashboard] --> F
```

This comprehensive diagram set illustrates the complete OPI architecture, from high-level flow to detailed component interactions, testing strategies, deployment procedures, and security considerations.
