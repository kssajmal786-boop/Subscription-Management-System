"""subscriptions/urls.py – Subscriptions & Plans routing with cross-module aliases"""
from django.urls import path
from . import views

app_name = "subscriptions"

urlpatterns = [
    # Plans
    path("plans/", views.plan_list, name="plan_list"),
    path("plans/create/", views.plan_create, name="plan_create"),
    path("plans/<int:pk>/edit/", views.plan_edit, name="plan_edit"),

    # Subscriptions – primary & aliases
    path("", views.subscription_list, name="subscription_list"),
    path("list/", views.subscription_list, name="list"),
    path("create/", views.subscription_create, name="subscription_create"),
    path("new/", views.subscription_create, name="create"),
    path("<int:pk>/", views.subscription_detail, name="subscription_detail"),
    path("<int:pk>/detail/", views.subscription_detail, name="detail"),
    path("<int:pk>/confirm/", views.subscription_confirm, name="subscription_confirm"),
    path("<int:pk>/confirm-action/", views.subscription_confirm, name="confirm"),
    path("<int:pk>/activate/", views.subscription_confirm, name="activate"),
    path("<int:pk>/pause/", views.subscription_pause, name="subscription_pause"),
    path("<int:pk>/pause-action/", views.subscription_pause, name="pause"),
    path("<int:pk>/resume/", views.subscription_resume, name="subscription_resume"),
    path("<int:pk>/resume-action/", views.subscription_resume, name="resume"),
    path("<int:pk>/close/", views.subscription_close, name="subscription_close"),
    path("<int:pk>/close-action/", views.subscription_close, name="close"),
    path("<int:pk>/renew/", views.subscription_renew, name="subscription_renew"),
    path("<int:pk>/renew-action/", views.subscription_renew, name="renew"),
    path("<int:pk>/accept/", views.quotation_accept_customer, name="quotation_accept"),
    path("<int:pk>/accept-action/", views.quotation_accept_customer, name="accept"),
    path("<int:pk>/toggle-autorenew/", views.subscription_toggle_autorenew, name="toggle_autorenew"),
]
