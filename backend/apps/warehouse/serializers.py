"""
仓库管理序列化器
"""
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    QuarantineCase, QuarantineInspection, QuarantineDecision, QuarantineMovement,
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    available_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    has_active_quarantine = serializers.BooleanField(read_only=True)

    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'quarantined_quantity', 'available_quantity',
            'has_active_quarantine', 'warning_threshold', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    
    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'stock_in_time', 'remark'
        ]


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 隔离处置 ====================

class QuarantineMovementSerializer(serializers.ModelSerializer):
    """隔离库存移动流水序列化器"""
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = QuarantineMovement
        fields = [
            'id', 'case', 'decision', 'movement_type', 'movement_type_display',
            'quantity', 'from_location', 'to_location', 'reverses',
            'operator', 'operator_name', 'note', 'created_at'
        ]


class QuarantineInspectionSerializer(serializers.ModelSerializer):
    """隔离复检记录序列化器"""
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    inspector_name = serializers.CharField(source='inspector.username', read_only=True)

    class Meta:
        model = QuarantineInspection
        fields = [
            'id', 'case', 'inspector', 'inspector_name',
            'result', 'result_display', 'conclusion',
            'inspected_at', 'created_at'
        ]


class QuarantineInspectionCreateSerializer(serializers.Serializer):
    """复检登记序列化器"""
    result = serializers.ChoiceField(
        choices=QuarantineInspection.RESULT_CHOICES,
        error_messages={'invalid_choice': '复检结果无效', 'required': '请选择复检结果'}
    )
    conclusion = serializers.CharField(error_messages={
        'required': '请填写复检结论',
        'blank': '复检结论不能为空',
    })


class QuarantineDecisionSerializer(serializers.ModelSerializer):
    """隔离处置决定序列化器"""
    decision_type_display = serializers.CharField(source='get_decision_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    proposed_by_name = serializers.CharField(source='proposed_by.username', read_only=True)
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    revoked_by_name = serializers.CharField(source='revoked_by.username', read_only=True)
    case_no = serializers.CharField(source='case.case_no', read_only=True)
    goods_name = serializers.CharField(source='case.goods.name', read_only=True)

    class Meta:
        model = QuarantineDecision
        fields = [
            'id', 'case', 'case_no', 'goods_name',
            'decision_type', 'decision_type_display', 'quantity', 'reason',
            'status', 'status_display',
            'proposed_by', 'proposed_by_name',
            'approver', 'approver_name', 'approval_opinion', 'approved_at',
            'revoked_by', 'revoked_by_name', 'revoke_reason', 'revoked_at',
            'created_at', 'updated_at'
        ]


class QuarantineDecisionCreateSerializer(serializers.Serializer):
    """处置决定申请序列化器"""
    decision_type = serializers.ChoiceField(
        choices=QuarantineDecision.TYPE_CHOICES,
        error_messages={'invalid_choice': '处置方式无效', 'required': '请选择处置方式'}
    )
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        error_messages={'required': '请填写处置数量'}
    )
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class QuarantineCaseSerializer(serializers.ModelSerializer):
    """隔离处置案件序列化器"""
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    found_by_name = serializers.CharField(source='found_by.username', read_only=True)
    disposed_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = QuarantineCase
        fields = [
            'id', 'case_no', 'goods', 'goods_name', 'goods_code', 'stock_in',
            'reason', 'reason_display', 'reason_detail',
            'quantity', 'remaining_quantity', 'disposed_quantity',
            'quarantine_location', 'status', 'status_display',
            'found_by', 'found_by_name', 'found_at', 'remark',
            'created_at', 'updated_at'
        ]


class QuarantineCaseDetailSerializer(QuarantineCaseSerializer):
    """隔离案件详情：携带复检、决定、流水与数量去向汇总"""
    inspections = QuarantineInspectionSerializer(many=True, read_only=True)
    decisions = QuarantineDecisionSerializer(many=True, read_only=True)
    movements = QuarantineMovementSerializer(many=True, read_only=True)
    quantity_breakdown = serializers.SerializerMethodField()

    class Meta(QuarantineCaseSerializer.Meta):
        fields = QuarantineCaseSerializer.Meta.fields + [
            'inspections', 'decisions', 'movements', 'quantity_breakdown'
        ]

    def get_quantity_breakdown(self, obj):
        from .services import case_quantity_breakdown
        breakdown = case_quantity_breakdown(obj)
        return {key: str(value) for key, value in breakdown.items()}


class QuarantineCaseCreateSerializer(serializers.Serializer):
    """隔离案件创建序列化器"""
    goods = serializers.IntegerField(error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        error_messages={'required': '请填写影响数量'}
    )
    reason = serializers.ChoiceField(
        choices=QuarantineCase.REASON_CHOICES,
        error_messages={'invalid_choice': '发现原因无效', 'required': '请选择发现原因'}
    )
    reason_detail = serializers.CharField(required=False, allow_blank=True, default='')
    stock_in = serializers.IntegerField(required=False, allow_null=True, default=None)
    quarantine_location = serializers.CharField(
        required=False, allow_blank=True, default='隔离区', max_length=100
    )
    remark = serializers.CharField(required=False, allow_blank=True, default='')


# ==================== 收发与转移 ====================

class StockInCreateSerializer(serializers.Serializer):
    """入库登记序列化器"""
    goods = serializers.IntegerField(error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        error_messages={'required': '请填写入库数量'}
    )
    batch_no = serializers.CharField(required=False, allow_blank=True, default='', max_length=50)
    supplier = serializers.CharField(required=False, allow_blank=True, default='', max_length=200)
    remark = serializers.CharField(required=False, allow_blank=True, default='')


class StockOutCreateSerializer(serializers.Serializer):
    """领用登记序列化器"""
    goods = serializers.IntegerField(error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        error_messages={'required': '请填写领用数量'}
    )
    receiver = serializers.CharField(max_length=100, error_messages={
        'required': '请填写领用人',
        'blank': '领用人不能为空',
    })
    receiver_dept = serializers.CharField(required=False, allow_blank=True, default='', max_length=100)
    remark = serializers.CharField(required=False, allow_blank=True, default='')


class GoodsTransferSerializer(serializers.Serializer):
    """货物转移序列化器"""
    location = serializers.CharField(max_length=100, error_messages={
        'required': '请填写目标位置',
        'blank': '目标位置不能为空',
    })
    remark = serializers.CharField(required=False, allow_blank=True, default='')
