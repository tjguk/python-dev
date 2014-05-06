@echo off
REM
REM This is intended to be a convenience file when the layout
REM is something like this:
REM
REM python\
REM   make.cmd (this file)
REM   python-make\
REM     make.py
REM     configure.ini
REM   issue12345\
REM     (a python clone)
REM   issue56789\
REM     (a different python clone)
REM
REM You would normally be inside one of the Python clones and then calling
REM ..\make
REM
FOR /F %%d IN ('%~d0%~p0\python-dev\clone.py %*') DO CD %%d
