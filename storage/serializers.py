from rest_framework import serializers
from .models import NoteItem


class NoteItemSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source='item_type', read_only=True)
    parentId = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    finalPrice = serializers.SerializerMethodField()

    class Meta:
        model = NoteItem
        fields = [
            'id',
            'name',
            'type',
            'parentId',
            's3_key',
            'url',
            'content_type',
            'size',
            'price',
            'discount_enabled',
            'discount_percent',
            'finalPrice',
            'created_at',
            'updated_at',
        ]

    def get_parentId(self, obj):
        return obj.parent_id

    def get_url(self, obj):
        if obj.item_type != 'file' or not obj.s3_key:
            return ''
        return self.context.get('file_urls', {}).get(obj.id, '')

    def get_finalPrice(self, obj):
        if obj.item_type != 'file':
            return 0
        if not obj.discount_enabled or obj.discount_percent <= 0:
            return obj.price
        discount_value = round((obj.price * obj.discount_percent) / 100)
        return max(obj.price - discount_value, 0)
