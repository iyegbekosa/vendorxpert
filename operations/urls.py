from django.urls import path

from . import api

urlpatterns = [
    path("api/site-config/", api.site_config_api, name="site_config_api"),
    path("api/support/tickets/", api.support_tickets_api, name="support_tickets_api"),
]
