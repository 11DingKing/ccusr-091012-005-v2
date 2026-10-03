"""
库房管理模型
"""
from django.db import models
from apps.authentication.models import User


class Unit(models.Model):
    """单位模型"""
    name = models.CharField('单位名称', max_length=5, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_units', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_unit'
        verbose_name = '单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品类"""
        return self.categories.exists()


class Category(models.Model):
    """品类模型"""
    name = models.CharField('品类名称', max_length=10, unique=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT,
        related_name='categories', verbose_name='单位'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_categories', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_category'
        verbose_name = '品类'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品种"""
        return self.varieties.exists()


class Variety(models.Model):
    """品种模型"""
    name = models.CharField('品种名称', max_length=20)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='varieties', verbose_name='所属品类'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_varieties', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_variety'
        verbose_name = '品种'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        unique_together = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    @property
    def is_in_stock(self):
        """是否已入库"""
        return self.goods.exists()
    
    @property
    def unit_name(self):
        """获取单位名称"""
        return self.category.unit.name if self.category and self.category.unit else ''


class Goods(models.Model):
    """货物模型"""
    variety = models.ForeignKey(
        Variety, on_delete=models.CASCADE,
        related_name='goods', verbose_name='所属品种'
    )
    name = models.CharField('货物名称', max_length=200)
    code = models.CharField('货物编码', max_length=50, unique=True)
    specification = models.CharField('规格型号', max_length=200, blank=True)
    quantity = models.DecimalField('库存数量', max_digits=12, decimal_places=2, default=0)
    quarantined_quantity = models.DecimalField('隔离数量', max_digits=12, decimal_places=2, default=0)
    warning_threshold = models.DecimalField('预警阈值', max_digits=12, decimal_places=2, default=10)
    location = models.CharField('存放位置', max_length=100, blank=True)
    remark = models.TextField('备注', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_goods'
        verbose_name = '货物'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def is_warning(self):
        """是否预警"""
        return self.quantity <= self.warning_threshold

    @property
    def available_quantity(self):
        """可用数量（库存中未被隔离冻结的部分）"""
        return self.quantity - self.quarantined_quantity

    @property
    def has_active_quarantine(self):
        """是否存在有效隔离（仍有数量处于隔离状态）"""
        return self.quarantined_quantity > 0


class StockIn(models.Model):
    """入库记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_ins', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    stock_in_time = models.DateTimeField('入库时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    
    class Meta:
        db_table = 'wh_stock_in'
        verbose_name = '入库记录'
        verbose_name_plural = verbose_name
        ordering = ['-stock_in_time']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class StockOut(models.Model):
    """出库记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_outs', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_out_operations', verbose_name='操作人'
    )
    receiver = models.CharField('领用人', max_length=100)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('出库数量', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    stock_out_time = models.DateTimeField('出库时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_stock_out'
        verbose_name = '出库记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class Warning(models.Model):
    """预警记录模型"""
    TYPE_CHOICES = [
        ('low_stock', '库存不足'),
        ('expiring', '即将过期'),
        ('expired', '已过期'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='warnings', verbose_name='货物'
    )
    type = models.CharField('预警类型', max_length=20, choices=TYPE_CHOICES)
    message = models.TextField('预警信息')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_warning'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.get_type_display()}"


class Approval(models.Model):
    """审批记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    
    stock_out = models.ForeignKey(
        StockOut, on_delete=models.CASCADE,
        related_name='approvals', verbose_name='出库记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approvals', verbose_name='审批人'
    )
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_approval'
        verbose_name = '审批记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.stock_out} - {self.get_status_display()}"


class QuarantineCase(models.Model):
    """隔离处置案件模型"""

    REASON_CHOICES = [
        ('package_damaged', '包装破损'),
        ('quality_suspect', '质量存疑'),
        ('expired', '已过期'),
        ('other', '其他'),
    ]

    STATUS_CHOICES = [
        ('open', '隔离中'),
        ('closed', '已结案'),
    ]

    case_no = models.CharField('案件编号', max_length=30, unique=True)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='quarantine_cases', verbose_name='货物'
    )
    stock_in = models.ForeignKey(
        'StockIn', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quarantine_cases', verbose_name='来源入库记录'
    )
    reason = models.CharField('发现原因', max_length=20, choices=REASON_CHOICES)
    reason_detail = models.TextField('原因说明', blank=True)
    quantity = models.DecimalField('影响数量', max_digits=12, decimal_places=2)
    remaining_quantity = models.DecimalField('剩余隔离数量', max_digits=12, decimal_places=2)
    quarantine_location = models.CharField('隔离位置', max_length=100, default='隔离区')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='open')
    found_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='found_quarantine_cases', verbose_name='发现人'
    )
    found_at = models.DateTimeField('发现时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_quarantine_case'
        verbose_name = '隔离处置案件'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.case_no} - {self.goods.name}"

    @property
    def disposed_quantity(self):
        """已处置数量（放行/退回/销毁的净额）"""
        return self.quantity - self.remaining_quantity


class QuarantineInspection(models.Model):
    """隔离复检记录模型"""

    RESULT_CHOICES = [
        ('pass', '复检合格'),
        ('fail', '复检不合格'),
        ('partial', '部分合格'),
    ]

    case = models.ForeignKey(
        QuarantineCase, on_delete=models.CASCADE,
        related_name='inspections', verbose_name='隔离案件'
    )
    inspector = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='quarantine_inspections', verbose_name='复检人'
    )
    result = models.CharField('复检结果', max_length=20, choices=RESULT_CHOICES)
    conclusion = models.TextField('复检结论')
    inspected_at = models.DateTimeField('复检时间', auto_now_add=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_quarantine_inspection'
        verbose_name = '隔离复检记录'
        verbose_name_plural = verbose_name
        ordering = ['-inspected_at']

    def __str__(self):
        return f"{self.case.case_no} - {self.get_result_display()}"


class QuarantineDecision(models.Model):
    """隔离处置决定模型"""

    TYPE_CHOICES = [
        ('release', '放行'),
        ('concession', '让步接收'),
        ('return', '退回'),
        ('destroy', '销毁'),
    ]

    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已执行'),
        ('rejected', '已拒绝'),
        ('revoked', '已撤销'),
    ]

    case = models.ForeignKey(
        QuarantineCase, on_delete=models.CASCADE,
        related_name='decisions', verbose_name='隔离案件'
    )
    decision_type = models.CharField('处置方式', max_length=20, choices=TYPE_CHOICES)
    quantity = models.DecimalField('处置数量', max_digits=12, decimal_places=2)
    reason = models.TextField('处置理由', blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    proposed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='proposed_quarantine_decisions', verbose_name='申请人'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_quarantine_decisions', verbose_name='审批人'
    )
    approval_opinion = models.TextField('审批意见', blank=True)
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    revoked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revoked_quarantine_decisions', verbose_name='撤销人'
    )
    revoke_reason = models.TextField('撤销原因', blank=True)
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_quarantine_decision'
        verbose_name = '隔离处置决定'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.case.case_no} - {self.get_decision_type_display()} {self.quantity}"


class QuarantineMovement(models.Model):
    """隔离库存移动流水模型（含反向动作，历史不删除）"""

    TYPE_CHOICES = [
        ('quarantine', '隔离入库'),
        ('release', '放行回库'),
        ('concession', '让步接收回库'),
        ('return', '退回出库'),
        ('destroy', '销毁出库'),
        ('revoke_release', '撤销放行'),
        ('revoke_concession', '撤销让步接收'),
        ('revoke_return', '撤销退回'),
        ('revoke_destroy', '撤销销毁'),
    ]

    case = models.ForeignKey(
        QuarantineCase, on_delete=models.CASCADE,
        related_name='movements', verbose_name='隔离案件'
    )
    decision = models.ForeignKey(
        QuarantineDecision, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements', verbose_name='关联决定'
    )
    movement_type = models.CharField('移动类型', max_length=20, choices=TYPE_CHOICES)
    quantity = models.DecimalField('移动数量', max_digits=12, decimal_places=2)
    from_location = models.CharField('移出位置', max_length=100, blank=True)
    to_location = models.CharField('移入位置', max_length=100, blank=True)
    reverses = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reversed_by', verbose_name='被冲销的流水'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='quarantine_movements', verbose_name='操作人'
    )
    note = models.TextField('说明', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_quarantine_movement'
        verbose_name = '隔离库存移动流水'
        verbose_name_plural = verbose_name
        ordering = ['id']

    def __str__(self):
        return f"{self.case.case_no} - {self.get_movement_type_display()} {self.quantity}"
