# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.tenants import router as tenant_router
from app.api.v1.auth import router as auth_router
from app.api.v1.subscriptions import router as subscription_router
from app.api.v1.payments import router as payment_router
from app.api.v1.sync import router as sync_router
from app.api.v1.sales import router as sales_router
from app.api.v1.stock import router as stock_router
from app.api.v1.clients import router as clients_router
from app.api.v1.reports import router as reports_router
from app.api.v1.payments_saas import router as saas_payments_router

from app.api.routes.pharmacies import router as pharmacies_router
from app.middleware.tenant_context import TenantContextMiddleware
from app.middleware.rate_limit_middleware import RateLimitMiddleware
# Ajouter les autres middlewares si besoin
# from app.middleware.audit_middleware import AuditMiddleware
# from app.middleware.auth_middleware import AuthMiddleware

app = FastAPI(
    title="EducApp Pharma SaaS",
    version="1.0.0"
)

# Middleware CORS d'abord
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À ajuster pour la production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ajouter tenant middleware
app.add_middleware(TenantContextMiddleware)

# Ajouter rate limit middleware
app.add_middleware(RateLimitMiddleware, request_limit=100, window_seconds=60)

# Ajouter d'autres middlewares si nécessaire
# app.add_middleware(AuditMiddleware)
# app.add_middleware(AuthMiddleware)

@app.get("/")
def root():
    return {"message": "Backend EducApp Pharma SaaS actif"}

@app.get("/health")
def health_check():
    """Endpoint de santé pour les load balancers"""
    return {"status": "healthy"}

# Inclure les routes
app.include_router(saas_payments_router)
app.include_router(tenant_router)
app.include_router(auth_router)  # Une seule fois
app.include_router(subscription_router)
app.include_router(payment_router)
app.include_router(sync_router)
app.include_router(sales_router)
app.include_router(stock_router)
app.include_router(clients_router)
app.include_router(reports_router)
app.include_router(pharmacies_router, prefix="/api/v1", tags=["pharmacies"])