from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("dashboard/", views.dashboard, name="dashboard"),
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
    path("ious/", views.ious, name="ious"),
    path("ious/lend/", views.add_lend, name="add_lend"),
    path("ious/borrow/", views.add_borrow, name="add_borrow"),
    path("ious/<int:pk>/", views.iou_detail, name="iou_detail"),
    path("converter/", views.currency_converter, name="currency_converter"),
    path("converter/rate/", views.converter_rate_api, name="converter_rate_api"),
    path("converter/convert/", views.converter_convert_api, name="converter_convert_api"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/clear-transactions/", views.clear_all_transactions, name="clear_all_transactions"),
    path("settings/clear-investments/", views.clear_all_investments, name="clear_all_investments"),
]
