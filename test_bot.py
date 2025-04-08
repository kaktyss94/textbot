import unittest
from datetime import time
from bot import get_random_paragraph, remove_page_numbers, read_schedule_from_file, save_schedule_to_file

class TestBotFunctions(unittest.TestCase):

    def test_get_random_paragraph(self):
        paragraph = get_random_paragraph("test_stoik.txt")
        self.assertIsInstance(paragraph, str)
        self.assertNotEqual(paragraph, "")

    def test_remove_page_numbers(self):
        text_with_numbers = "Страница 123. Это текст с номерами 456."
        cleaned_text = remove_page_numbers(text_with_numbers)
        self.assertEqual(cleaned_text, "Это текст с номерами.")

    def test_read_schedule_from_file(self):
        times = read_schedule_from_file("test_schedule.txt")
        self.assertIsInstance(times, list)
        self.assertTrue(all(isinstance(t, time) for t in times))

    def test_save_schedule_to_file(self):
        test_times = [time(9, 0), time(18, 0)]
        save_schedule_to_file("test_schedule.txt", test_times)
        with open("test_schedule.txt", "r", encoding="utf-8") as file:
            lines = file.readlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0].strip(), "09:00")
            self.assertEqual(lines[1].strip(), "18:00")

if __name__ == "__main__":
    unittest.main()