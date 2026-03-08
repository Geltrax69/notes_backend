from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health, name='health'),
    path('search/', views.search_items, name='search-items'),
    path('admin/stats/', views.admin_stats, name='admin-stats'),
    path('admin/recent-purchases/', views.admin_recent_purchases, name='admin-recent-purchases'),
    path('auth/google/', views.google_auth, name='google-auth'),
    path('auth/manual/', views.manual_auth, name='manual-auth'),
    path('users/me/', views.user_me, name='user-me'),
    path('items/', views.items_list, name='items-list'),
    path('items/<int:item_id>/', views.item_detail, name='item-detail'),
    path('folders/', views.create_folder, name='create-folder'),
    path('files/', views.upload_pdf, name='upload-pdf'),
    path('files/<int:item_id>/content/', views.file_content, name='file-content'),
    path('files/<int:item_id>/price/', views.update_file_price, name='update-file-price'),
    path('items/<int:item_id>/delete/', views.delete_item, name='delete-item'),
    path('purchases/', views.my_purchases, name='my-purchases'),
    path('payments/config/', views.payment_config, name='payment-config'),
    path('payments/order/', views.create_payment_order, name='payment-order'),
    path('payments/verify/', views.verify_payment, name='payment-verify'),
]
