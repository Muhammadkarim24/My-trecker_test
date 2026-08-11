class Driver:
    def __init__(self, name, age, experience):
        self.name = name
        self.age = age
        self.experience = experience
class Car:
    def __init__(self, model, year, color):
        self.year = year
        self.model = model
        self.color = color

        driver = Driver('Amiri', 22, 12) 
        opel = Car('Astra', 2021, 'blue')   
    # def set_driver(self, driver:Driver):
            
        

print(opel.model,opel.color, opel.year, "\n")
print(driver.age, driver.experience, driver.name)