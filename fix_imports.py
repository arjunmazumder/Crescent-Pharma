import os

files = [
    'api/apps.py',
    'core/apps.py',
    'hr/apps.py',
    'users/apps.py',
    'crescent_pharma/settings.py',
    'crescent_pharma/urls.py',
    'crescent_pharma/asgi.py',
    'api/serializers.py',
    'api/views.py',
    'api/routing.py',
    'hr/models.py',
    'hr/tasks.py'
]

for file in files:
    path = os.path.join(r'd:\circle-Seed\Crescent-Pharma-Django', file)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Specific replacements to avoid breaking things
        content = content.replace('apps.api', 'api')
        content = content.replace('apps.core', 'core')
        content = content.replace('apps.hr', 'hr')
        content = content.replace('apps.users', 'users')
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {file}")
