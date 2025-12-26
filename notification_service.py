import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from uuid import UUID

from twilio.rest import Client
from app.core.config import settings
from app.models.sale import Sale
from app.models.client import Client
from app.models.user import User

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service de notifications pour l'application PharmaSaaS
    Gère les SMS, WhatsApp, emails et notifications internes
    """
    
    def __init__(self, db: Session):
        self.db = db
        self._twilio_client = None
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialise les clients de notification"""
        try:
            # Initialisation Twilio
            if hasattr(settings, "TWILIO_SID") and hasattr(settings, "TWILIO_AUTH_TOKEN"):
                if settings.TWILIO_SID and settings.TWILIO_AUTH_TOKEN:
                    self._twilio_client = Client(settings.TWILIO_SID, settings.TWILIO_AUTH_TOKEN)
                    logger.info("Client Twilio initialisé avec succès")
        except Exception as e:
            logger.error(f"Erreur initialisation clients de notification: {e}")
    
    async def send_sale_confirmation(self, sale: Sale) -> Dict[str, Any]:
        """
        Envoie une confirmation de vente au vendeur et gestionnaires
        """
        try:
            result = {
                "to_seller": False,
                "to_managers": False,
                "messages": []
            }
            
            # Récupérer le vendeur
            seller = self.db.query(User).filter(User.id == sale.created_by).first()
            
            # Notification au vendeur
            if seller and seller.telephone:
                message_body = (
                    f"✅ Vente #{sale.reference} confirmée\n"
                    f"Montant: {sale.total_amount:.2f} {settings.CURRENCY}\n"
                    f"Client: {sale.client_name}\n"
                    f"Méthode: {sale.payment_method}\n"
                    f"Date: {sale.created_at.strftime('%d/%m/%Y %H:%M')}"
                )
                
                if self.send_sms(to=seller.telephone, body=message_body):
                    result["to_seller"] = True
                    result["messages"].append({
                        "recipient": seller.nom_complet,
                        "type": "sms",
                        "status": "sent"
                    })
            
            # Notification aux gestionnaires pour les grosses ventes
            if sale.total_amount > 100000:  # Seuil configurable
                managers = self.db.query(User).filter(
                    User.role.in_(["admin", "gerant"]),
                    User.is_active == True,
                    User.telephone.isnot(None)
                ).all()
                
                for manager in managers:
                    if manager.id != seller.id:  # Ne pas notifier le vendeur à nouveau
                        manager_message = (
                            f"💰 Vente importante #{sale.reference}\n"
                            f"Montant: {sale.total_amount:.2f} {settings.CURRENCY}\n"
                            f"Vendeur: {seller.nom_complet if seller else 'N/A'}\n"
                            f"Client: {sale.client_name}"
                        )
                        
                        if self.send_sms(to=manager.telephone, body=manager_message):
                            result["to_managers"] = True
                            result["messages"].append({
                                "recipient": manager.nom_complet,
                                "type": "sms",
                                "status": "sent"
                            })
            
            return result
            
        except Exception as e:
            logger.error(f"Erreur envoi confirmation vente: {e}")
            return {"error": str(e)}
    
    async def send_customer_receipt(self, sale: Sale) -> Dict[str, Any]:
        """
        Envoie le reçu au client
        """
        try:
            result = {
                "sms_sent": False,
                "whatsapp_sent": False,
                "message_id": None
            }
            
            # Préparer le message du reçu
            receipt_body = (
                f"📋 Reçu de votre achat chez {settings.APP_NAME}\n"
                f"--------------------------------\n"
                f"Référence: {sale.reference}\n"
                f"Date: {sale.created_at.strftime('%d/%m/%Y %H:%M')}\n"
                f"Montant: {sale.total_amount:.2f} {settings.CURRENCY}\n"
                f"Méthode: {sale.payment_method}\n"
                f"Merci pour votre confiance !"
            )
            
            # Envoi SMS
            if sale.client_phone:
                if self.send_sms(to=sale.client_phone, body=receipt_body):
                    result["sms_sent"] = True
            
            # Envoi WhatsApp si disponible
            if sale.client_phone and self._twilio_client:
                if self.send_whatsapp(to=sale.client_phone, body=receipt_body):
                    result["whatsapp_sent"] = True
            
            return result
            
        except Exception as e:
            logger.error(f"Erreur envoi reçu client: {e}")
            return {"error": str(e)}
    
    async def send_stock_alert(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Envoie une alerte de stock bas
        """
        try:
            managers = self.db.query(User).filter(
                User.role.in_(["admin", "gerant", "pharmacien"]),
                User.is_active == True,
                User.telephone.isnot(None)
            ).all()
            
            alert_body = (
                f"⚠️ ALERTE STOCK - {product_data['product_name']}\n"
                f"Code: {product_data['product_code']}\n"
                f"Stock restant: {product_data['current_stock']}\n"
                f"Seuil: {product_data['alert_threshold']}\n"
                f"Status: {product_data['status'].upper()}"
            )
            
            results = []
            for manager in managers:
                if self.send_sms(to=manager.telephone, body=alert_body):
                    results.append({
                        "manager": manager.nom_complet,
                        "sent": True
                    })
                else:
                    results.append({
                        "manager": manager.nom_complet,
                        "sent": False
                    })
            
            return {
                "alert_type": "low_stock",
                "product": product_data['product_name'],
                "results": results,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erreur envoi alerte stock: {e}")
            return {"error": str(e)}
    
    async def send_expiry_alert(self, expiry_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Envoie une alerte de péremption
        """
        try:
            if not expiry_data:
                return {"message": "Aucun produit en alerte"}
            
            # Grouper par jours restants
            critical = [p for p in expiry_data if p['days_remaining'] <= 7]
            warning = [p for p in expiry_data if 7 < p['days_remaining'] <= 30]
            
            managers = self.db.query(User).filter(
                User.role.in_(["admin", "gerant", "pharmacien"]),
                User.is_active == True,
                User.telephone.isnot(None)
            ).all()
            
            results = []
            for manager in managers:
                # Message pour produits critiques
                if critical:
                    critical_body = (
                        f"🚨 ALERTE CRITIQUE - Produits périmes bientôt\n"
                        f"--------------------------------\n"
                    )
                    for product in critical[:3]:  # Limiter à 3 produits
                        critical_body += (
                            f"- {product['product_name']}: "
                            f"{product['days_remaining']} jour(s)\n"
                        )
                    
                    if self.send_sms(to=manager.telephone, body=critical_body):
                        results.append({
                            "manager": manager.nom_complet,
                            "type": "critical",
                            "sent": True
                        })
                
                # Message pour avertissements
                if warning and not critical:  # Envoyer seulement si pas d'alerte critique
                    warning_body = (
                        f"⚠️ AVERTISSEMENT - Produits approchant péremption\n"
                        f"--------------------------------\n"
                    )
                    for product in warning[:3]:
                        warning_body += (
                            f"- {product['product_name']}: "
                            f"{product['days_remaining']} jour(s)\n"
                        )
                    
                    if self.send_sms(to=manager.telephone, body=warning_body):
                        results.append({
                            "manager": manager.nom_complet,
                            "type": "warning",
                            "sent": True
                        })
            
            return {
                "alert_type": "expiry",
                "critical_count": len(critical),
                "warning_count": len(warning),
                "results": results
            }
            
        except Exception as e:
            logger.error(f"Erreur envoi alerte péremption: {e}")
            return {"error": str(e)}
    
    async def send_credit_payment_reminder(self, client: Client) -> Dict[str, Any]:
        """
        Envoie un rappel de paiement crédit
        """
        try:
            if not client.telephone:
                return {"error": "Client sans numéro de téléphone"}
            
            overdue_invoices = [
                sale for sale in client.sales 
                if sale.is_credit and sale.credit_due_date < datetime.utcnow().date()
                and sale.status != "paid"
            ]
            
            if not overdue_invoices:
                return {"message": "Aucune facture en retard"}
            
            total_overdue = sum(sale.total_amount for sale in overdue_invoices)
            
            reminder_body = (
                f"🔔 Rappel de paiement - {settings.APP_NAME}\n"
                f"--------------------------------\n"
                f"Cher(e) {client.nom_complet},\n"
                f"Vous avez {len(overdue_invoices)} facture(s) en retard.\n"
                f"Montant total dû: {total_overdue:.2f} {settings.CURRENCY}\n"
                f"Veuillez régulariser votre situation.\n"
                f"Merci."
            )
            
            if self.send_sms(to=client.telephone, body=reminder_body):
                return {
                    "sent": True,
                    "client": client.nom_complet,
                    "overdue_count": len(overdue_invoices),
                    "total_amount": float(total_overdue)
                }
            
            return {"sent": False}
            
        except Exception as e:
            logger.error(f"Erreur envoi rappel crédit: {e}")
            return {"error": str(e)}
    
    def send_sms(self, to: str, body: str, from_: str = None) -> bool:
        """
        Envoie un SMS via Twilio
        """
        if not self._twilio_client:
            logger.warning("Twilio non configuré, SMS non envoyé")
            return False
        
        try:
            # Formater le numéro
            if not to.startswith('+'):
                to = f"+243{to.lstrip('0')}"  # Format Congo par défaut
            
            message = self._twilio_client.messages.create(
                body=body,
                from_=from_ or settings.TWILIO_PHONE_NUMBER,
                to=to
            )
            
            logger.info(f"SMS envoyé à {to}: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur envoi SMS à {to}: {e}")
            return False
    
    def send_whatsapp(self, to: str, body: str, from_: str = None) -> bool:
        """
        Envoie un message WhatsApp via Twilio
        """
        if not self._twilio_client:
            logger.warning("Twilio non configuré, WhatsApp non envoyé")
            return False
        
        try:
            # Formater le numéro
            if not to.startswith('whatsapp:+'):
                if to.startswith('+'):
                    to = f"whatsapp:{to}"
                else:
                    to = f"whatsapp:+243{to.lstrip('0')}"
            
            message = self._twilio_client.messages.create(
                body=body,
                from_=from_ or f"whatsapp:{settings.TWILIO_WHATSAPP_NUMBER}",
                to=to
            )
            
            logger.info(f"WhatsApp envoyé à {to}: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur envoi WhatsApp à {to}: {e}")
            return False
    
    async def send_bulk_notifications(self, 
                                     notifications: List[Dict[str, Any]],
                                     notification_type: str = "generic") -> Dict[str, Any]:
        """
        Envoie des notifications en masse
        """
        try:
            results = {
                "total": len(notifications),
                "successful": 0,
                "failed": 0,
                "details": []
            }
            
            for notification in notifications:
                try:
                    if notification_type == "sms":
                        sent = self.send_sms(
                            to=notification.get('to'),
                            body=notification.get('body')
                        )
                    elif notification_type == "whatsapp":
                        sent = self.send_whatsapp(
                            to=notification.get('to'),
                            body=notification.get('body')
                        )
                    else:
                        sent = False
                    
                    if sent:
                        results["successful"] += 1
                    else:
                        results["failed"] += 1
                    
                    results["details"].append({
                        "recipient": notification.get('to'),
                        "sent": sent
                    })
                    
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({
                        "recipient": notification.get('to'),
                        "error": str(e)
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Erreur notifications en masse: {e}")
            return {"error": str(e)}
    
    def get_notification_status(self) -> Dict[str, Any]:
        """
        Retourne le statut des services de notification
        """
        return {
            "twilio_configured": self._twilio_client is not None,
            "sms_enabled": hasattr(settings, "SMS_ENABLED") and settings.SMS_ENABLED,
            "whatsapp_enabled": hasattr(settings, "WHATSAPP_ENABLED") and settings.WHATSAPP_ENABLED,
            "currency": settings.CURRENCY if hasattr(settings, "CURRENCY") else "USD",
            "app_name": settings.APP_NAME if hasattr(settings, "APP_NAME") else "PharmaSaaS",
            "timestamp": datetime.utcnow().isoformat()
        }


# Fonctions de compatibilité (pour l'import existant)
def send_sms(to: str, body: str, from_: str = None) -> bool:
    """
    Fonction de compatibilité pour l'envoi de SMS
    """
    service = NotificationService(None)  # Session vide pour compatibilité
    return service.send_sms(to, body, from_)


def send_whatsapp(to: str, body: str, from_: str = None) -> bool:
    """
    Fonction de compatibilité pour l'envoi WhatsApp
    """
    service = NotificationService(None)  # Session vide pour compatibilité
    return service.send_whatsapp(to, body, from_)