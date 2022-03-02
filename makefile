run:
	python3 manage.py runserver 0.0.0.0:5556

generate:
	python3 manage.py makemigrations && python3 manage.py migrate