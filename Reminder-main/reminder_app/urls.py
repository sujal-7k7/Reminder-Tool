from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("create/", views.create_reminder, name="create_reminder"),
    path("edit/<int:reminder_id>/", views.edit_reminder, name="edit_reminder"),
    path("delete/<int:reminder_id>/", views.delete_reminder, name="delete_reminder"),
    path("pause/<int:reminder_id>/", views.toggle_pause, name="toggle_pause"),
    path("logout/", views.logout_view, name="logout"),
    path("contact/", views.contact, name="contact"),
    path("category-master/", views.category_master, name="category_master"),
    path("create-user/", views.create_user, name="create_user"),
    path("profile/", views.profile, name="profile"),
    path("users/", views.users_list, name="users_list"),
    path("edit-user/<int:user_id>/", views.edit_user, name="edit_user"),
    path("delete-user/<int:user_id>/", views.delete_user, name="delete_user"),
    path('calendar/', views.calendar_view, name='calendar_view'),
  
]