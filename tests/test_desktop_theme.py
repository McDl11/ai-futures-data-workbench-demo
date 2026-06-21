import unittest

from desktop.theme import ThemeMode, choose_theme_mode, theme_tokens


class DesktopThemeTests(unittest.TestCase):
    def test_choose_theme_mode_uses_override(self):
        self.assertEqual(choose_theme_mode("light", windows_light_setting=0), ThemeMode.LIGHT)
        self.assertEqual(choose_theme_mode("dark", windows_light_setting=1), ThemeMode.DARK)

    def test_choose_theme_mode_follows_windows_setting(self):
        self.assertEqual(choose_theme_mode("system", windows_light_setting=1), ThemeMode.LIGHT)
        self.assertEqual(choose_theme_mode("system", windows_light_setting=0), ThemeMode.DARK)

    def test_choose_theme_mode_defaults_to_light_when_unknown(self):
        self.assertEqual(choose_theme_mode("system", windows_light_setting=None), ThemeMode.LIGHT)
        self.assertEqual(choose_theme_mode("unexpected", windows_light_setting=0), ThemeMode.LIGHT)

    def test_theme_tokens_have_required_contrast_colors(self):
        light = theme_tokens(ThemeMode.LIGHT)
        dark = theme_tokens(ThemeMode.DARK)

        for tokens in (light, dark):
            self.assertTrue(tokens.background)
            self.assertTrue(tokens.surface)
            self.assertTrue(tokens.text)
            self.assertTrue(tokens.accent)

        self.assertNotEqual(light.background, dark.background)
        self.assertNotEqual(light.text, dark.text)


if __name__ == "__main__":
    unittest.main()
