"""
仓库管理序列化器
"""
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    QuarantineCase, QuarantineUnit, QuarantineReinspection,
    QuarantineApproval, QuarantineDisposition, QuarantineRevocation,
    StockMovement,
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
    quarantined_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()

    def get_quarantined_quantity(self, obj):
        return str(obj.quarantined_quantity)

    def get_available_quantity(self, obj):
        return str(obj.available_quantity)

    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'quarantined_quantity', 'available_quantity',
            'warning_threshold', 'location',
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


# ==================== 隔离处置案件 ====================

class QuarantineCaseCreateSerializer(serializers.Serializer):
    """立案序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    stock_in = serializers.IntegerField(required=False, allow_null=True)
    batch_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    discovery_reason = serializers.ChoiceField(
        choices=[
            ('package_damaged', '包装破损'),
            ('label_missing', '标识缺失'),
            ('quality_abnormal', '质量异常'),
            ('quantity_shortage', '数量短少'),
            ('other', '其他'),
        ],
        required=True, error_messages={'required': '请选择发现原因', 'invalid_choice': '发现原因不合法'}
    )
    reason_detail = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    affected_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        error_messages={'required': '请填写影响数量', 'invalid': '影响数量不合法'}
    )
    quarantine_location = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value

    def validate_stock_in(self, value):
        if value and not StockIn.objects.filter(pk=value).exists():
            raise serializers.ValidationError('入库记录不存在')
        return value

    def validate_affected_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError('影响数量必须大于0')
        return value


class QuarantineUnitSerializer(serializers.ModelSerializer):
    """处置单元序列化器：每一数量单位的当前处置状态"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    goods = serializers.SerializerMethodField()

    def get_goods(self, obj):
        return obj.case.goods_id

    class Meta:
        model = QuarantineUnit
        fields = [
            'id', 'case', 'goods', 'seq', 'quantity',
            'status', 'status_display', 'hold_active',
            'hold_quantity', 'released_quantity', 'concession_quantity',
            'returned_quantity', 'remark', 'updated_at'
        ]


class QuarantineReinspectionSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(source='inspector.username', read_only=True)
    result_display = serializers.CharField(source='get_result_display', read_only=True)

    class Meta:
        model = QuarantineReinspection
        fields = [
            'id', 'case', 'inspector', 'inspector_name',
            'result', 'result_display',
            'qualified_quantity', 'concession_quantity', 'unqualified_quantity',
            'finding', 'inspected_at'
        ]
        read_only_fields = ['inspector']


class QuarantineReinspectionCreateSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=QuarantineReinspection.Result.choices,
        required=True, error_messages={'required': '请选择复检结果'}
    )
    qualified_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    concession_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    unqualified_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    finding = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class StockMovementSerializer(serializers.ModelSerializer):
    move_type_display = serializers.CharField(source='get_move_type_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    is_effective = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            'id', 'case', 'approval', 'reverses',
            'move_type', 'move_type_display', 'goods',
            'quantity', 'from_location', 'to_location',
            'operator', 'operator_name', 'remark',
            'is_reversed', 'is_effective', 'created_at'
        ]


class QuarantineApprovalSerializer(serializers.ModelSerializer):
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    decision_display = serializers.CharField(source='get_decision_display', read_only=True)
    is_revoked = serializers.BooleanField(read_only=True)
    dispositions = serializers.SerializerMethodField()

    def get_dispositions(self, obj):
        return [
            {
                'id': d.id,
                'unit': d.unit_id,
                'unit_seq': d.unit.seq,
                'kind': d.kind,
                'kind_display': d.get_kind_display(),
                'quantity': str(d.quantity),
                'movement': d.movement_id,
                'is_reversed': d.is_reversed,
                'reversed_at': d.reversed_at,
            }
            for d in obj.dispositions.select_related('unit').all()
        ]

    class Meta:
        model = QuarantineApproval
        fields = [
            'id', 'case', 'reinspection', 'approver', 'approver_name',
            'decision', 'decision_display', 'quantity',
            'target_location', 'opinion', 'is_revoked',
            'dispositions', 'created_at'
        ]


class QuarantineDecisionCreateSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=QuarantineApproval.Decision.choices,
        required=True, error_messages={'required': '请选择审批决定', 'invalid_choice': '审批决定不合法'}
    )
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        error_messages={'required': '请填写处置数量'}
    )
    target_location = serializers.CharField(max_length=100, required=False, allow_blank=True)
    opinion = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    reinspection = serializers.IntegerField(required=False, allow_null=True)


class QuarantineRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class QuarantineCaseSerializer(serializers.ModelSerializer):
    """隔离处置案件序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    discoverer_name = serializers.CharField(source='discoverer.username', read_only=True)
    discovery_reason_display = serializers.CharField(source='get_discovery_reason_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    held_quantity = serializers.SerializerMethodField()
    released_quantity = serializers.SerializerMethodField()
    concession_quantity = serializers.SerializerMethodField()
    returned_quantity = serializers.SerializerMethodField()

    def _q(self, value):
        return str(value)

    def get_held_quantity(self, obj):
        return self._q(obj.held_quantity)

    def get_released_quantity(self, obj):
        return self._q(obj.released_quantity)

    def get_concession_quantity(self, obj):
        return self._q(obj.concession_quantity)

    def get_returned_quantity(self, obj):
        return self._q(obj.returned_quantity)

    class Meta:
        model = QuarantineCase
        fields = [
            'id', 'code', 'goods', 'goods_name', 'goods_code',
            'stock_in', 'batch_no',
            'discoverer', 'discoverer_name', 'discovered_at',
            'discovery_reason', 'discovery_reason_display', 'reason_detail',
            'affected_quantity', 'quarantine_location', 'origin_location',
            'status', 'status_display',
            'held_quantity', 'released_quantity',
            'concession_quantity', 'returned_quantity',
            'closed_at', 'created_at', 'updated_at'
        ]


class StockOutCreateSerializer(serializers.Serializer):
    """领用申请序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        error_messages={'required': '请填写领用数量'}
    )
    receiver = serializers.CharField(max_length=100, required=True, error_messages={'required': '请填写领用人'})
    receiver_dept = serializers.CharField(max_length=100, required=False, allow_blank=True)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value


class StockTransferCreateSerializer(serializers.Serializer):
    """库位转移序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        error_messages={'required': '请填写转移数量'}
    )
    to_location = serializers.CharField(max_length=100, required=True,
                                        error_messages={'required': '请填写目标库位'})
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value
