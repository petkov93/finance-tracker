from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("add/", views.add_transaction, name="add_transaction"),
    path("edit/<int:pk>/", views.edit_transaction, name="edit_transaction"),
    path("delete/<int:pk>/", views.delete_transaction, name="delete_transaction"),
    path("statistics/", views.statistics, name="statistics"),
    path("investments/", views.investments, name="investments"),
    path("investments/add/", views.add_investment, name="add_investment"),
    path("investments/edit/<int:pk>/", views.edit_investment, name="edit_investment"),
    path("investments/delete/<int:pk>/", views.delete_investment, name="delete_investment"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/clear-transactions/", views.clear_all_transactions, name="clear_all_transactions"),
    path("settings/clear-investments/", views.clear_all_investments, name="clear_all_investments"),
]
