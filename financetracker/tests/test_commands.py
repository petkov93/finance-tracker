from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from financetracker.models import Category
from financetracker.tests.factories import create_category


class SeedCategoriesCommandTests(TestCase):
    def test_creates_defaults_on_empty_database(self):
        out = StringIO()
        call_command("seed_categories", stdout=out)

        self.assertEqual(Category.objects.count(), 13)
        self.assertTrue(Category.objects.filter(name="Salary", type="income").exists())
        self.assertTrue(Category.objects.filter(name="Food", type="expense").exists())
        self.assertTrue(Category.objects.filter(name="Lending", type="expense").exists())
        self.assertIn("Created 13 default categories.", out.getvalue())

    def test_skips_when_categories_already_exist(self):
        create_category(name="Custom")
        out = StringIO()
        call_command("seed_categories", stdout=out)

        self.assertEqual(Category.objects.count(), 1)
        self.assertIn("Categories already exist", out.getvalue())
