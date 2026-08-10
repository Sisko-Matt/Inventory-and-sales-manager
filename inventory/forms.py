from django import forms
from django.forms import inlineformset_factory

from .models import Category, Supplier, Product, Order, OrderItem


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-control"})}


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone_number", "email", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
        }


class ProductForm(forms.ModelForm):
    # Not a model field - a one-time acknowledgement checkbox. See
    # Product.clean() in models.py for why this rule lives here in the
    # form rather than as an unconditional model invariant.
    override_low_price = forms.BooleanField(
        required=False,
        label="I confirm this selling price is intentionally below cost price",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "supplier",
            "cost_price",
            "selling_price",
            "quantity_in_stock",
            "low_stock_threshold",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "cost_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "selling_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "quantity_in_stock": forms.NumberInput(attrs={"class": "form-control"}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        cost_price = cleaned_data.get("cost_price")
        selling_price = cleaned_data.get("selling_price")
        override = cleaned_data.get("override_low_price")

        if (
            cost_price is not None
            and selling_price is not None
            and selling_price < cost_price
            and not override
        ):
            self.add_error(
                "selling_price",
                f"Selling price ({selling_price}) is below cost price "
                f"({cost_price}). Check the override box below if this is "
                f"intentional.",
            )
        return cleaned_data

    @property
    def is_price_override(self):
        """True if this form was submitted with a below-cost price that
        the override checkbox explicitly waived through. Read by the view
        after a successful save() to decide whether to write a
        PriceOverrideLog entry."""
        cost_price = self.cleaned_data.get("cost_price")
        selling_price = self.cleaned_data.get("selling_price")
        return (
            cost_price is not None
            and selling_price is not None
            and selling_price < cost_price
        )


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["customer_name", "customer_phone"]
        widgets = {
            "customer_name": forms.TextInput(attrs={"class": "form-control"}),
            "customer_phone": forms.TextInput(attrs={"class": "form-control"}),
        }


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        # selling_price is intentionally excluded - it's snapshotted from
        # product.selling_price in the view when the order is created,
        # not typed in by staff. See OrderItem model docstring.
        fields = ["product", "quantity"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        }

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than zero.")
        return quantity


# A formset lets one Order have a variable number of OrderItem rows on a
# single page. extra=3 shows three empty rows to start; can_delete lets
# staff remove a row they added by mistake before submitting.
OrderItemFormSet = inlineformset_factory(
    Order,
    OrderItem,
    form=OrderItemForm,
    extra=3,
    can_delete=True,
)
