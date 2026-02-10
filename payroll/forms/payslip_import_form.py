from django import forms

class PayslipImportForm(forms.Form):
    """
    यह सुनिश्चित करता है कि क्लास का नाम (PayslipImportForm) 
    __init__.py में उपयोग किए गए नाम से बिल्कुल मेल खाता हो।
    """
    import_file = forms.FileField(
        label='Select Payslip File (CSV/Excel)', 
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )


class EmployeeImportForm(forms.Form):
    """
    Form for importing employees for payroll processing.
    """
    file = forms.FileField(label='Select a file')