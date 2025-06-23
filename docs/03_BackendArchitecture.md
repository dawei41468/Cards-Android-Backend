# Backend Architecture & Model Alignment Strategy

## 1. Overview

This document outlines the architecture for the CardGameApp backend and the strategy for aligning models between the backend and Android frontend. The goal is to create a maintainable, scalable backend that can evolve independently of the frontend while ensuring smooth interoperability.

## 2. Core Principles

1. **Separation of Concerns**: Clear boundaries between different layers of the application
2. **Maintainability**: Code should be easy to understand, test, and modify
3. **Scalability**: Architecture should support growth in features and users
4. **Performance**: Efficient data handling and minimal overhead
5. **Security**: Proper validation and authentication at all layers

## 3. Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │     │                 │
│  API Endpoints  │◄───►│  API Schemas    │◄───►│  Domain Models  │
│  (FastAPI)      │     │  (Pydantic)     │     │  (Pure Python)  │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │     │                 │
│  WebSocket      │◄───►│  Event Handlers │◄───►│  Game Logic     │
│  (Socket.IO)    │     │                 │     │  (Domain)       │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │     │                 │
│  MongoDB        │◄───►│  DB Models      │◄───►│  Repositories   │
│  (Pymongo)      │     │  (ODM)          │     │  (Data Access)  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## 4. Model Layers

### 4.1 Domain Models (`app/models/domain/`)

- Pure business logic models
- No database or API concerns
- Similar to frontend models but with backend-specific fields
- Examples: `Card`, `Player`, `GameState`, `GameRoom`

### 4.2 Database Models (`app/models/db/`)

- Map to MongoDB documents
- Include database-specific fields (`_id`, `created_at`, etc.)
- Methods to convert to/from domain models
- Example:
  ```python
  class DBCard(BaseModel):
      _id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
      suit: str
      rank: str
      created_at: datetime = Field(default_factory=datetime.utcnow)
  ```

### 4.3 API Schemas (`app/schemas/`)

- Pydantic models for request/response validation
- Methods to convert to/from domain models
- Can be versioned for API evolution
- Example:
  ```python
  class CardCreate(BaseModel):
      suit: str
      rank: str
  ```

## 5. Model Alignment Strategy

### 5.1 Frontend-Backend Alignment

| Frontend Model | Backend Domain Model | Notes |
|----------------|----------------------|-------|
| `Card` | `domain.Card` | Keep simple with suit/rank |
| `GameState` | `domain.GameState` | Align field names (camelCase vs snake_case) |
| `Player` | `domain.Player` | Add backend-specific fields |
| `GameRoom` | `domain.GameRoom` | Include status and settings |

### 5.2 Transformation Layer

Create mappers to convert between layers:

```python
# Example mapper
class CardMapper:
    @staticmethod
    def to_domain(api_card: schemas.CardCreate) -> domain.Card:
        return domain.Card(
            suit=api_card.suit,
            rank=api_card.rank
        )
    
    @staticmethod
    def to_db(domain_card: domain.Card) -> db_models.DBCard:
        return db_models.DBCard(
            suit=domain_card.suit,
            rank=domain_card.rank
        )
```

## 6. API Design Guidelines

1. **Naming Conventions**:
   - Use `camelCase` for JSON properties
   - Use `snake_case` for Python code

2. **Versioning**:
   - Include API version in URL path (`/api/v1/...`)
   - Use content negotiation for versioning when appropriate

3. **Error Handling**:
   - Consistent error response format
   - Appropriate HTTP status codes
   - Detailed error messages in development

## 7. WebSocket Integration

1. **Authentication**:
   - Use JWT for WebSocket authentication
   - Validate tokens on connection

2. **Events**:
   - Define clear event contracts
   - Document event payloads
   - Handle reconnection logic

## 8. Security Considerations

1. **Input Validation**:
   - Validate all inputs at API boundaries
   - Use Pydantic for request validation

2. **Authentication**:
   - JWT for both REST and WebSocket
   - Token expiration and refresh

3. **Data Protection**:
   - Never expose sensitive data in responses
   - Implement proper access controls

## 9. Testing Strategy

1. **Unit Tests**:
   - Test domain models and business logic
   - Mock external dependencies

2. **Integration Tests**:
   - Test API endpoints
   - Test database interactions

3. **End-to-End Tests**:
   - Test complete user flows
   - Include WebSocket communication

## 10. Future Considerations

1. **Caching**:
   - Implement Redis for caching frequent queries
   - Cache game state for active games

2. **Scaling**:
   - Horizontal scaling with multiple backend instances
   - Database sharding for large-scale deployment

3. **Monitoring**:
   - Add logging and metrics
   - Set up alerts for errors and performance issues

## 11. Implementation Plan

1. **Phase 1**: Refactor backend structure
   - Create model layers
   - Implement transformation layer
   - Update API endpoints

2. **Phase 2**: Update WebSocket handlers
   - Align event payloads
   - Implement proper error handling

3. **Phase 3**: Testing and validation
   - Write unit and integration tests
   - Perform end-to-end testing with frontend

4. **Phase 4**: Documentation and deployment
   - Update API documentation
   - Prepare for production deployment
