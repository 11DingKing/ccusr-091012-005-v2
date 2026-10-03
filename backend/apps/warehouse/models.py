"""
库房管理模型
"""
from decimal import Decimal

from django.db import models, transaction
from apps.authentication.models import User

QUANTITY_UNIT = Decimal('1.00')


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
    def quarantined_quantity(self):
        """当前处于有效隔离中的数量（由隔离处置单元汇总，不单独记账）"""
        if hasattr(self, '_quarantined_total'):
            return self._quarantined_total or Decimal('0')
        total = QuarantineUnit.objects.filter(
            case__goods=self, hold_active=True
        ).aggregate(total=models.Sum('hold_quantity'))['total']
        return total or Decimal('0')

    @property
    def available_quantity(self):
        """可领用/转移数量：总库存扣除有效隔离数量"""
        available = self.quantity - self.quarantined_quantity
        return available if available > 0 else Decimal('0')

    def assert_movable(self, quantity):
        """校验领用/转移数量是否触碰有效隔离，触碰则抛出业务异常。

        调用方须先以 select_for_update 锁定货物行（在 services 的事务内完成），
        避免并发事务同时按旧库存通过校验。
        """
        from apps.core.exceptions import BusinessException
        quantity = Decimal(str(quantity))
        if quantity > self.available_quantity:
            raise BusinessException(
                f'货物存在有效隔离数量 {self.quarantined_quantity}，'
                f'可操作数量仅 {self.available_quantity}，本次申请 {quantity} 已被阻断',
                code=409
            )


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


# ==================== 隔离处置案件 ====================

class QuarantineCase(models.Model):
    """隔离处置案件：将包装破损等异常发现串成可追溯处置流程。"""

    class Disposition(models.TextChoices):
        PENDING = 'pending', '待复检'
        REINSPECTED = 'reinspected', '已复检待审批'
        RELEASED = 'released', '部分放行'
        CONCESSION = 'concession', '让步接收'
        RETURNED = 'returned', '退回'
        REVOKED = 'revoked', '已撤销'

    code = models.CharField('案件编号', max_length=32, unique=True, blank=True)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='quarantine_cases', verbose_name='货物'
    )
    stock_in = models.ForeignKey(
        StockIn, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quarantine_cases', verbose_name='入库记录'
    )
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    discoverer = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='discovered_quarantine_cases', verbose_name='发现人'
    )
    discovered_at = models.DateTimeField('发现时间', auto_now_add=True)
    discovery_reason = models.CharField(
        '发现原因', max_length=30,
        choices=[
            ('package_damaged', '包装破损'),
            ('label_missing', '标识缺失'),
            ('quality_abnormal', '质量异常'),
            ('quantity_shortage', '数量短少'),
            ('other', '其他'),
        ]
    )
    reason_detail = models.TextField('原因说明', blank=True)
    affected_quantity = models.DecimalField('影响数量', max_digits=12, decimal_places=2)
    quarantine_location = models.CharField('隔离位置', max_length=100, default='隔离区')
    origin_location = models.CharField('原存放位置', max_length=100, blank=True)
    status = models.CharField(
        '案件状态', max_length=20,
        choices=Disposition.choices, default=Disposition.PENDING
    )
    closed_at = models.DateTimeField('结案时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_quarantine_case'
        verbose_name = '隔离处置案件'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} - {self.goods.name}'

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_code():
        from django.utils import timezone
        prefix = 'QC' + timezone.now().strftime('%Y%m%d%H%M%S%f')[:17]
        # 极端并发下保证唯一
        code = prefix
        seq = 1
        while QuarantineCase.objects.filter(code=code).exists():
            code = f'{prefix}{seq:02d}'
            seq += 1
        return code

    @property
    def held_quantity(self):
        """仍处于隔离中的数量"""
        total = self.units.filter(hold_active=True).aggregate(
            total=models.Sum('hold_quantity'))['total']
        return total or Decimal('0')

    @property
    def released_quantity(self):
        total = self.units.aggregate(
            total=models.Sum('released_quantity'))['total']
        return total or Decimal('0')

    @property
    def concession_quantity(self):
        total = self.units.aggregate(
            total=models.Sum('concession_quantity'))['total']
        return total or Decimal('0')

    @property
    def returned_quantity(self):
        total = self.units.aggregate(
            total=models.Sum('returned_quantity'))['total']
        return total or Decimal('0')


class QuarantineUnit(models.Model):
    """隔离处置单元：案件影响数量按单位拆分成的最小处置/追踪单位。"""

    class Status(models.TextChoices):
        HELD = 'held', '隔离中'
        PARTIAL = 'partial', '部分处置中（剩余隔离）'
        RELEASED = 'released', '已放行'
        CONCESSION = 'concession', '让步接收'
        RETURNED = 'returned', '已退回'

    case = models.ForeignKey(
        QuarantineCase, on_delete=models.PROTECT,
        related_name='units', verbose_name='所属案件'
    )
    seq = models.PositiveIntegerField('单元序号')
    quantity = models.DecimalField('单元数量', max_digits=12, decimal_places=2, default=QUANTITY_UNIT)
    status = models.CharField(
        '处置状态', max_length=20, choices=Status.choices, default=Status.HELD
    )
    hold_active = models.BooleanField('隔离是否有效', default=True, db_index=True)
    hold_quantity = models.DecimalField(
        '有效隔离数量', max_digits=12, decimal_places=2, default=QUANTITY_UNIT
    )
    released_quantity = models.DecimalField(
        '累计放行数量', max_digits=12, decimal_places=2, default=Decimal('0')
    )
    concession_quantity = models.DecimalField(
        '累计让步接收数量', max_digits=12, decimal_places=2, default=Decimal('0')
    )
    returned_quantity = models.DecimalField(
        '累计退回数量', max_digits=12, decimal_places=2, default=Decimal('0')
    )
    remark = models.CharField('备注', max_length=200, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_quarantine_unit'
        verbose_name = '隔离处置单元'
        verbose_name_plural = verbose_name
        ordering = ['case_id', 'seq']
        unique_together = ['case', 'seq']

    def __str__(self):
        return f'{self.case.code}-{self.seq:04d}（{self.get_status_display()}）'

    @property
    def goods(self):
        return self.case.goods

    _COUNTER_BY_KIND = {
        'release': 'released_quantity',
        'concession': 'concession_quantity',
        'return': 'returned_quantity',
    }
    _STATUS_BY_KIND = {
        'release': Status.RELEASED,
        'concession': Status.CONCESSION,
        'return': Status.RETURNED,
    }

    def _refresh_status(self):
        disposed = self.released_quantity + self.concession_quantity + self.returned_quantity
        if disposed == 0:
            self.status = self.Status.HELD
        elif self.hold_quantity == 0:
            self.hold_active = False
            # 全部按同一种方式处置时显示该终态，混合处置按最先落账的类型显示
            for kind, counter in self._COUNTER_BY_KIND.items():
                if getattr(self, counter) > 0:
                    self.status = self._STATUS_BY_KIND[kind]
                    break
        else:
            # 仍有剩余数量保持隔离
            self.status = self.Status.PARTIAL

    def apply_disposition(self, kind, quantity):
        """处置数量落账。部分处置时剩余数量仍保持有效隔离。"""
        from apps.core.exceptions import BusinessException
        quantity = Decimal(str(quantity))
        if quantity <= 0 or quantity > self.hold_quantity:
            raise BusinessException('处置数量必须大于0且不超过该单元有效隔离数量')
        counter = self._COUNTER_BY_KIND[kind]
        setattr(self, counter, getattr(self, counter) + quantity)
        self.hold_quantity -= quantity
        if self.hold_quantity == 0:
            self.hold_active = False
        self._refresh_status()
        self.save()

    def revert_disposition(self, kind, quantity):
        """撤销处置：数量退回有效隔离，历史累计清零对应部分。"""
        from apps.core.exceptions import BusinessException
        quantity = Decimal(str(quantity))
        counter = self._COUNTER_BY_KIND[kind]
        current = getattr(self, counter)
        if quantity <= 0 or quantity > current:
            raise BusinessException('撤销数量超过该处置类型的累计数量')
        setattr(self, counter, current - quantity)
        self.hold_quantity += quantity
        self.hold_active = True
        self._refresh_status()
        self.save()


class QuarantineReinspection(models.Model):
    """复检记录：每次复检结论独立留痕，供审批引用。"""

    class Result(models.TextChoices):
        PENDING = 'pending', '待复检'
        QUALIFIED = 'qualified', '复检合格（可放行）'
        CONCESSION = 'concession', '让步可用'
        UNQUALIFIED = 'unqualified', '复检不合格（建议退回）'

    case = models.ForeignKey(
        QuarantineCase, on_delete=models.PROTECT,
        related_name='reinspections', verbose_name='所属案件'
    )
    inspector = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='quarantine_reinspections', verbose_name='复检人'
    )
    result = models.CharField('复检结果', max_length=20, choices=Result.choices)
    qualified_quantity = models.DecimalField(
        '复检合格数量', max_digits=12, decimal_places=2, default=Decimal('0')
    )
    concession_quantity = models.DecimalField(
        '让步数量', max_digits=12, decimal_places=2, default=Decimal('0')
    )
    unqualified_quantity = models.DecimalField(
        '不合格数量', max_digits=12, decimal_places=2, default=Decimal('0')
    )
    finding = models.TextField('复检情况', blank=True)
    inspected_at = models.DateTimeField('复检时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_quarantine_reinspection'
        verbose_name = '复检记录'
        verbose_name_plural = verbose_name
        ordering = ['-inspected_at']

    def __str__(self):
        return f'{self.case.code} - {self.get_result_display()}'


class QuarantineApproval(models.Model):
    """隔离处置审批意见：决定放行/让步接收/退回。"""

    class Decision(models.TextChoices):
        RELEASE = 'release', '准予放行'
        CONCESSION = 'concession', '让步接收'
        RETURN = 'return', '退回供应商'

    case = models.ForeignKey(
        QuarantineCase, on_delete=models.PROTECT,
        related_name='approvals', verbose_name='所属案件'
    )
    reinspection = models.ForeignKey(
        QuarantineReinspection, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approvals', verbose_name='依据复检记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='quarantine_approvals', verbose_name='审批人'
    )
    decision = models.CharField('审批决定', max_length=20, choices=Decision.choices)
    quantity = models.DecimalField('决定处置数量', max_digits=12, decimal_places=2)
    target_location = models.CharField('放行/让步入库位置', max_length=100, blank=True)
    opinion = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('审批时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_quarantine_approval'
        verbose_name = '隔离处置审批'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.case.code} - {self.get_decision_display()} {self.quantity}'

    @property
    def is_revoked(self):
        return hasattr(self, 'revocation')


class QuarantineDisposition(models.Model):
    """处置落账：一次审批在某个处置单元上生效的数量及对应库存移动。

    撤销审批时据此把数量加回有效隔离，并反向冲销移动，历史不删除。
    """

    class Kind(models.TextChoices):
        RELEASE = 'release', '放行'
        CONCESSION = 'concession', '让步接收'
        RETURN = 'return', '退回'

    approval = models.ForeignKey(
        QuarantineApproval, on_delete=models.PROTECT,
        related_name='dispositions', verbose_name='审批决定'
    )
    unit = models.ForeignKey(
        QuarantineUnit, on_delete=models.PROTECT,
        related_name='dispositions', verbose_name='处置单元'
    )
    movement = models.ForeignKey(
        'StockMovement', on_delete=models.PROTECT,
        related_name='dispositions', verbose_name='库存移动'
    )
    kind = models.CharField('处置类型', max_length=20, choices=Kind.choices)
    quantity = models.DecimalField('处置数量', max_digits=12, decimal_places=2)
    reversed_at = models.DateTimeField('撤销时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_quarantine_disposition'
        verbose_name = '处置落账'
        verbose_name_plural = verbose_name
        ordering = ['created_at']

    def __str__(self):
        return f'{self.approval.case.code}-{self.unit.seq:04d} {self.get_kind_display()} {self.quantity}'

    @property
    def is_reversed(self):
        return self.reversed_at is not None


class QuarantineRevocation(models.Model):
    """撤销记录：撤销一次处置审批，留存撤销原因与操作人。"""

    approval = models.OneToOneField(
        QuarantineApproval, on_delete=models.PROTECT,
        related_name='revocation', verbose_name='被撤销的审批'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='quarantine_revocations', verbose_name='撤销操作人'
    )
    reason = models.TextField('撤销原因', blank=True)
    created_at = models.DateTimeField('撤销时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_quarantine_revocation'
        verbose_name = '处置撤销记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'撤销审批 {self.approval_id}（案件 {self.approval.case.code}）'


class StockMovement(models.Model):
    """库存移动：隔离引发的每一次实物移动均记账，撤销生成反向动作而非删除。"""

    class MoveType(models.TextChoices):
        QUARANTINE_IN = 'quarantine_in', '移入隔离区'
        QUARANTINE_OUT = 'quarantine_out', '移出隔离区（放行/让步）'
        RETURN_OUT = 'return_out', '退回出库'
        TRANSFER = 'transfer', '库位转移'
        REVERSAL = 'reversal', '撤销反向移动'

    case = models.ForeignKey(
        QuarantineCase, on_delete=models.PROTECT, null=True, blank=True,
        related_name='movements', verbose_name='所属案件'
    )
    approval = models.ForeignKey(
        QuarantineApproval, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements', verbose_name='来源审批'
    )
    reverses = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='reversed_by', verbose_name='被撤销的原移动'
    )
    move_type = models.CharField('移动类型', max_length=20, choices=MoveType.choices)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='stock_movements', verbose_name='货物'
    )
    quantity = models.DecimalField('移动数量', max_digits=12, decimal_places=2)
    from_location = models.CharField('来源位置', max_length=100, blank=True)
    to_location = models.CharField('目标位置', max_length=100, blank=True)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_movements', verbose_name='操作人'
    )
    remark = models.TextField('备注', blank=True)
    is_reversed = models.BooleanField('是否已被撤销', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_stock_movement'
        verbose_name = '库存移动'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_move_type_display()} {self.goods.name} {self.quantity}'

    @property
    def is_effective(self):
        """当前是否生效（未被撤销，且本身不是反向动作）。"""
        return not self.is_reversed and self.move_type != self.MoveType.REVERSAL

    @classmethod
    def record(cls, case, move_type, quantity, operator, from_location='',
               to_location='', approval=None, remark=''):
        """登记移动并同步库存账面（退回扣减库存，隔离内移动不动账面总量）。"""
        from apps.core.exceptions import BusinessException
        quantity = Decimal(str(quantity))
        with transaction.atomic():
            goods = Goods.objects.select_for_update().get(pk=case.goods_id)
            if move_type == cls.MoveType.RETURN_OUT and quantity > goods.quantity:
                raise BusinessException('退回数量超过货物库存总量')
            movement = cls.objects.create(
                case=case, approval=approval, move_type=move_type, goods=goods,
                quantity=quantity, from_location=from_location, to_location=to_location,
                operator=operator, remark=remark
            )
            update_fields = ['updated_at']
            if move_type == cls.MoveType.RETURN_OUT:
                goods.quantity -= quantity
                update_fields.append('quantity')
            goods.save(update_fields=update_fields)
            return goods, movement

    def reverse(self, operator, remark=''):
        """生成反向移动。返回退库时补回库存；任何历史记录均不删除。"""
        from apps.core.exceptions import BusinessException
        if self.move_type == self.MoveType.REVERSAL:
            raise BusinessException('反向移动不能再次撤销')
        if self.is_reversed:
            raise BusinessException('该移动已被撤销')
        if self.reversed_by.exists():
            raise BusinessException('该移动已存在反向动作')
        with transaction.atomic():
            locked_self = type(self).objects.select_for_update().get(pk=self.pk)
            if locked_self.is_reversed:
                raise BusinessException('该移动已被撤销')
            goods = Goods.objects.select_for_update().get(pk=self.goods_id)
            reversal = type(self).objects.create(
                case=self.case, approval=self.approval, reverses=self,
                move_type=StockMovement.MoveType.REVERSAL, goods=goods,
                quantity=self.quantity,
                from_location=self.to_location, to_location=self.from_location,
                operator=operator,
                remark=remark or f'撤销移动 {self.id} 的反向动作'
            )
            # 原动作是退回出库 -> 反向补回库存
            if self.move_type == StockMovement.MoveType.RETURN_OUT:
                goods.quantity += self.quantity
                goods.save(update_fields=['quantity', 'updated_at'])
            locked_self.is_reversed = True
            locked_self.save(update_fields=['is_reversed'])
            return goods, reversal
