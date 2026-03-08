from django.contrib import admin
from .models import NoteItem


@admin.register(NoteItem)
class NoteItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'item_type', 'parent', 's3_key', 'created_at')
    search_fields = ('name', 's3_key')
    list_filter = ('item_type',)
